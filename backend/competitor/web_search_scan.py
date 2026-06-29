"""
Web-search-first competitor scan (primary scan method).

For each product in the master catalog:
  1. Build a search query from title / model number / manufacturer
  2. Query DuckDuckGo, Bing, Google, Yahoo concurrently
  3. Collect up to max_results unique URLs (excluding source domains)
  4. Skip URLs whose domain is in a 3-day no-results cooldown
  5. Fetch each URL via httpx (fast, no Playwright); extract product info
     from JSON-LD schema.org markup, Open Graph tags, and meta price tags
  6. Match extracted product against the master catalog
  7. Auto-create Competitor records for newly-discovered domains
  8. Store CompetitorProductMatch / PriceHistory records

The old per-competitor site scrape remains available as a backup method.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from backend.competitor.matcher import MatchCriteria, MatchResult, match_competitor_product, match_similar_product
from backend.database.db import session_scope
from backend.database.models import (
    Competitor,
    CompetitorProductMatch,
    CompetitorScrapingProfile,
    PriceHistory,
    Product,
)
from backend.search.core.fetch import _curl_get
from backend.search.core.parse import (
    _domain,
    _extract_price_float as _extract_price,
    _parse_jsonld,
    _parse_meta,
)
from backend.search.core.rank import multi_engine_search

logger = logging.getLogger(__name__)

COOLDOWN_DAYS = 3
_FETCH_CONCURRENCY = 10
_SEARCH_CONCURRENCY = 5
_CHECKPOINT_THRESHOLD = 100  # emit a checkpoint event after this many URLs visited

_stop_requested: bool = False


def request_stop() -> None:
    global _stop_requested
    _stop_requested = True

# Note: this _MODEL_RE is narrower than core/parse._MODEL_RE on purpose — it only
# matches explicit "model/part/item #" labels in result snippets. Kept local.
_MODEL_RE = re.compile(r'(?:model|part|item)[#\s:]+([A-Z0-9][\w\-]{2,})', re.I)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GENERIC_MANUFACTURERS: frozenset = frozenset({
    'multiple vendors', 'various', 'generic', 'n/a', 'unknown', 'assorted',
})


def _clean_title_for_search(title: str) -> str:
    """Strip noise from product titles to produce clean search queries."""
    # Remove everything inside parentheses: (00799579), (APPROX- 226 DOZEN/HR), (4), etc.
    title = re.sub(r'\([^)]*\)', '', title)
    # Compound voltage/frequency specs with V suffix: 208-240v/60/3-ph, 480V/60Hz/3Ph, 208v
    title = re.sub(r'\b\d+[-/]?\d*\s*[Vv]\b(?:[-/]\d+[\w-]*)*', '', title)
    # Standalone electrical tokens: 60Hz, 3ph, 3-phase, 1-Ph, 5kW
    # NOTE: no trailing [\w/-]* — that greedily ate "/1" from "60Hz/1 Ph", orphaning "Ph"
    title = re.sub(r'\b\d+\s*[-]?\s*(?:hz|ph|phase|kw|kva)\b', '', title, flags=re.I)
    # Slash-paired voltage ranges left behind after unit removal: 208/240, 400/480
    # Require ≥2 digits each side to avoid swallowing "1/2" fractions in specs like "1/2 HP"
    title = re.sub(r'\b\d{2,}/\d{2,}\b', '', title)
    # Remove leading package/size codes: "Small 5.1 ", "3.1-"
    title = re.sub(r'^(?:Small|Medium|Large)?\s*\d+\.\d+[-\s]', '', title, flags=re.I)
    # Remove standalone part numbers (all-caps/digits with dashes, 6+ chars)
    title = re.sub(r'\b[A-Z0-9]{2,}-[A-Z0-9\-]{3,}\b', '', title)
    # Strip leftover punctuation: commas, standalone dashes, slashes, colons
    title = re.sub(r'[,;:/]', ' ', title)
    title = re.sub(r'(?<!\w)-|-(?!\w)', ' ', title)  # dash not flanked by word chars
    title = ' '.join(title.split())
    # Trim to ~60 chars at a word boundary
    if len(title) > 60:
        words = title.split()
        result, length = [], 0
        for word in words:
            if length + len(word) + (1 if result else 0) > 60:
                break
            result.append(word)
            length += len(word) + (1 if len(result) > 1 else 0)
        title = ' '.join(result)
    return title.strip()


def _build_query(product: Product) -> str:
    parts: List[str] = []
    mfr = (product.manufacturer or '').strip()
    # Treat generic/placeholder manufacturer values as absent
    if mfr.lower() in _GENERIC_MANUFACTURERS:
        mfr = ''

    # When a user-curated search term exists it leads the query — the editable
    # field's whole purpose is to catch competitors a narrow model/SKU query
    # misses. Still cleaned so the default (combined store titles) stays usable.
    search_term = (getattr(product, 'product_search_term', '') or '').strip()
    if search_term:
        cleaned = _clean_title_for_search(search_term)
        term_parts: List[str] = []
        if mfr and mfr.lower() not in cleaned.lower():
            term_parts.append(mfr)
        if cleaned:
            term_parts.append(cleaned)
        term_parts.append('buy')
        return ' '.join(' '.join(term_parts).split())

    # Prefer model_number (quoted for precision); fall back to SKU (unquoted —
    # SKUs with multiple hyphens don't index well as exact phrases); then title.
    if mfr and product.model_number:
        model = re.sub(r'[^\w\-]', '', product.model_number)
        parts.append(mfr)
        parts.append(f'"{model}"')
    elif product.model_number:
        model = re.sub(r'[^\w\-]', '', product.model_number)
        parts.append(f'"{model}"')
    elif getattr(product, 'sku', None):
        sku = re.sub(r'[^\w\-]', '', product.sku)
        if mfr:
            parts.append(mfr)
        parts.append(sku)
    else:
        title = _clean_title_for_search(product.canonical_title or '')
        if mfr:
            # Remove full manufacturer phrase then individual words so "BELSHAW" is
            # stripped when the manufacturer is "Belshaw Adamatic" and vice-versa
            title = re.sub(r'(?i)\b' + re.escape(mfr) + r'\b', '', title)
            for word in mfr.split():
                if len(word) > 3:
                    title = re.sub(r'(?i)\b' + re.escape(word) + r'\b', '', title)
            title = ' '.join(title.split())
            parts.append(mfr)
        if title:
            parts.append(title)
    parts.append('buy')
    return ' '.join(parts)


def _extract_model(text: str) -> Optional[str]:
    m = _MODEL_RE.search(text or '')
    return m.group(1).strip() if m else None


async def _fetch_product_data(url: str) -> Optional[Dict[str, Any]]:
    """Fetch a product page and extract structured data. Returns None on failure.

    Fetch + parse both route through the shared core (core/fetch, core/parse) so
    this scan and the per-product scan extract identical fields from a page.
    """
    html = await _curl_get(url)
    if not html:
        return None
    data = _parse_jsonld(html) or _parse_meta(html)
    if data:
        data['url'] = url
        data['source_site'] = _domain(url)
    return data


_CATEGORY_KEYWORDS_BASE = frozenset({
    # Commercial bakery / foodservice equipment — supplement product-derived categories
    'commercial mixer', 'planetary mixer', 'spiral mixer', 'floor mixer',
    'commercial oven', 'convection oven', 'deck oven', 'rack oven', 'revolving oven',
    'proofer', 'proof box', 'retarder proofer',
    'donut fryer', 'commercial fryer', 'donut equipment',
    'donut glaz', 'icing machine', 'glazing machine',
    'donut depositor', 'dough depositor',
    'bread slicer', 'dough divider', 'dough sheeter', 'dough rounder',
    'display case', 'bakery display', 'refrigerated display',
    'sheet pan', 'baking pan', 'bun pan',
    'bakery equipment', 'bakery supplies', 'bakery wholesale',
    'food service equipment', 'commercial kitchen', 'restaurant equipment',
    'cake decorating', 'decorating supplies', 'pastry',
    'packaging', 'bakery box', 'pastry box',
    'donut shop', 'bakery',
})


def _build_category_keywords(db_categories: list) -> frozenset:
    """Combine DB product categories with the hardcoded base keyword set."""
    derived = set()
    for cat in db_categories:
        if not cat:
            continue
        for part in re.split(r'[/,|>]', cat.lower()):
            part = part.strip()
            if len(part) >= 4:
                derived.add(part)
    return _CATEGORY_KEYWORDS_BASE | frozenset(derived)


def _is_manufacturer_domain(domain: str, manufacturer_names: frozenset) -> bool:
    """True if the domain name is a fuzzy match for a known manufacturer's brand."""
    # Normalize: strip TLD, dashes, spaces
    d = re.sub(r'\.(com|net|org|us|co|biz|info|shop|store)$', '', domain.lower())
    d = re.sub(r'[^a-z0-9]', '', d)
    for mfr in manufacturer_names:
        mfr_clean = re.sub(r'[^a-z0-9]', '', mfr.lower())
        if len(mfr_clean) < 4:
            continue
        if mfr_clean in d or d.startswith(mfr_clean[:6]):
            return True
    return False


def _is_in_cooldown(profile: Optional[CompetitorScrapingProfile], force: bool = False) -> bool:
    """Return True if this competitor's empty-scan cooldown is still active."""
    if force or profile is None:
        return False
    if profile.last_empty_scan_at is None:
        return False
    cutoff = profile.last_empty_scan_at + timedelta(days=COOLDOWN_DAYS)
    return datetime.utcnow() < cutoff


def _get_source_domains() -> set:
    """Load source domains from config so we can exclude them from results."""
    try:
        from backend.config import config
        sites = config.get('source_sites') or []
        return {s['domain'] for s in sites if s.get('domain')}
    except Exception:
        return {'donut-supplies.com', 'donut-equipment.com', 'bakerywholesalers.com'}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_web_search_scan(
    session_name: str,
    max_results: int = 20,
    product_limit: Optional[int] = None,
    product_ids: Optional[List[int]] = None,
    callbacks: Optional[List[Callable]] = None,
    force: bool = False,
    selected_engines: Optional[set] = None,
) -> dict:
    """
    Run a full web-search-first scan across the product catalog.

    Args:
        session_name: Label for this scan run.
        max_results: Number of search-result URLs to visit per product (1–100).
        product_ids: Limit to specific product IDs; None = all active products.
        callbacks: List of async (event, data) callables for progress events.
        force: Ignore 3-day cooldown for all competitors.
        selected_engines: Set of engine keys to restrict the search to, or None
            for all engines (the default).

    Returns:
        Summary dict with total_products, total_urls_visited, total_matches.
    """
    global _stop_requested
    _stop_requested = False
    max_results = max(1, min(100, max_results))
    cbs = callbacks or []
    source_domains = _get_source_domains()

    async def emit(event: str, data: dict) -> None:
        for cb in cbs:
            try:
                await cb(event, data)
            except Exception:
                pass

    # --- Load products + build domain intelligence sets ---
    with session_scope() as db:
        from sqlalchemy import or_ as _or
        q = db.query(Product).filter(Product.is_active == True)
        if product_ids:
            q = q.filter(Product.id.in_(product_ids))
        q = q.order_by(Product.price_canonical.desc().nullslast())
        if product_limit:
            q = q.limit(product_limit)
        products = q.all()
        product_snapshots = [
            {
                'id': p.id,
                'title': p.canonical_title,
                'search_term': p.product_search_term,
                'manufacturer': p.manufacturer,
                'model_number': p.model_number,
                'sku': p.sku,
                'price': p.price_canonical,
                'category': p.category,
            }
            for p in products
        ]

        # Domains to skip entirely this scan: source sites + explicitly excluded + manufacturers
        excluded_comps = db.query(Competitor).filter(
            _or(Competitor.excluded_from_search == True, Competitor.is_manufacturer == True)
        ).all()
        skip_domains: set = source_domains | {c.domain for c in excluded_comps}

        # Unique manufacturer names for domain fuzzy-matching
        manufacturer_names: frozenset = frozenset(
            p.manufacturer for p in
            db.query(Product).filter(Product.is_active == True, Product.manufacturer != None).all()
            if p.manufacturer
        )

        # Category keywords derived from product categories + hardcoded base
        db_categories = [
            p.category for p in
            db.query(Product).filter(Product.is_active == True, Product.category != None).all()
            if p.category
        ]
    category_keywords = _build_category_keywords(db_categories)

    total_products = len(product_snapshots)
    logger.info("[WEB-SCAN] Starting web search scan: %d products, max_results=%d", total_products, max_results)
    await emit('web_search_scan_start', {'total_products': total_products, 'session_name': session_name})

    total_urls_visited = 0
    total_matches = 0
    search_sem = asyncio.Semaphore(_SEARCH_CONCURRENCY)
    fetch_sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

    criteria = MatchCriteria()

    async def process_product(snap: dict) -> tuple[int, int]:
        """Search for one product, visit URLs, store matches. Returns (urls_visited, matches)."""
        nonlocal total_urls_visited, total_matches

        # Build a fake Product for the matcher (use snapshot dict)
        class _FakeProduct:
            def __init__(self, s: dict):
                self.id = s['id']
                self.canonical_title = s['title']
                self.product_search_term = s.get('search_term')
                self.manufacturer = s['manufacturer']
                self.model_number = s['model_number']
                self.sku = s['sku']
                self.price_canonical = s['price']
                self.category = s['category']
                self.images = []

        fake = _FakeProduct(snap)

        query = _build_query(fake)

        logger.info("[WEB-SCAN] Searching: product=%r  query=%r", snap['title'], query)

        async with search_sem:
            search_results = await multi_engine_search(
                query=query,
                max_results=max_results,
                exclude_domains=skip_domains,
                engines=list(selected_engines) if selected_engines else None,
                match_pct=30,
                log_label=f"competitor scan · {snap['title'][:32]}",
            )

        logger.info("[WEB-SCAN] Search returned %d results for %r", len(search_results), snap['title'])

        if not search_results:
            logger.info("[WEB-SCAN] No search results for %r — skipping", snap['title'])
            return 0, 0

        urls_visited = 0
        matches = 0

        async def visit_url(item: dict) -> None:
            nonlocal urls_visited, matches
            url = item.get('href') or item.get('url', '')
            if not url:
                return
            domain = _domain(url)
            if not domain:
                return

            async def _log(status: str) -> None:
                await emit('web_search_url_attempted', {
                    'url': url,
                    'domain': domain,
                    'status': status,
                    'product_title': snap['title'],
                })

            # Fast-path: skip domains already known to be irrelevant this scan
            if domain in skip_domains:
                logger.debug("[WEB-SCAN] Skipping %s — in skip list", domain)
                await _log('skipped')
                return

            # Check DB status and cooldown
            with session_scope() as db:
                competitor = db.query(Competitor).filter(Competitor.domain == domain).first()
                if competitor:
                    if competitor.excluded_from_search or competitor.is_manufacturer:
                        skip_domains.add(domain)
                        await _log('skipped')
                        return
                    if competitor.scraping_profile and _is_in_cooldown(competitor.scraping_profile, force=force):
                        logger.debug("[WEB-SCAN] Skipping %s (3-day cooldown)", domain)
                        await _log('cooldown')
                        return

            # Manufacturer domain detection — skip OEM websites, record them so we never revisit
            if _is_manufacturer_domain(domain, manufacturer_names):
                logger.info("[WEB-SCAN] Skipping %s — detected as manufacturer domain", domain)
                skip_domains.add(domain)
                with session_scope() as db:
                    if not db.query(Competitor).filter(Competitor.domain == domain).first():
                        db.add(Competitor(
                            domain=domain, name=domain, base_url=f"https://{domain}",
                            is_manufacturer=True, excluded_from_search=True, is_active=False,
                        ))
                await _log('manufacturer')
                return

            logger.info("[WEB-SCAN] Visiting %s  (product=%r)", domain, snap['title'])
            async with fetch_sem:
                page_data = await _fetch_product_data(url)

            urls_visited += 1

            if not page_data or not page_data.get('title'):
                page_data = {
                    'title': item.get('title', ''),
                    'price': _extract_price(item.get('body', '')),
                    'model_number': _extract_model(item.get('body', '')),
                    'manufacturer': None,
                    'sku': None,
                    'in_stock': True,
                    'url': url,
                    'source_site': domain,
                }

            raw_mfr = page_data.get('manufacturer')
            if isinstance(raw_mfr, list):
                raw_mfr = raw_mfr[0] if raw_mfr else None
            if isinstance(raw_mfr, dict):
                raw_mfr = raw_mfr.get('name') or raw_mfr.get('@value') or None
            comp_dict = {
                'title': page_data.get('title', ''),
                'price': page_data.get('price'),
                'model_number': page_data.get('model_number'),
                'manufacturer': raw_mfr if isinstance(raw_mfr, str) else None,
                'sku': page_data.get('sku'),
                'description': item.get('body', ''),
                'image_hash': None,
            }

            _url_status = 'no_match'
            with session_scope() as db:
                master_products = db.query(Product).filter(Product.is_active == True).all()
                result = match_competitor_product(comp_dict, master_products, criteria)
                if result is None:
                    result = match_similar_product(comp_dict, master_products)

                if result is None:
                    # No product match — check for category-level relevance signals
                    snippet = ' '.join([
                        item.get('title', ''),
                        item.get('body', ''),
                        page_data.get('title', ''),
                    ]).lower()
                    is_category_hit = any(kw in snippet for kw in category_keywords)

                    existing = db.query(Competitor).filter(Competitor.domain == domain).first()
                    if existing:
                        # Upgrade to category competitor if we see relevant content
                        if is_category_hit and not existing.is_category_only and not existing.excluded_from_search:
                            existing.is_category_only = True
                            logger.info("[WEB-SCAN] Upgraded %s to category competitor", domain)
                    else:
                        new_comp = Competitor(
                            domain=domain, name=domain, base_url=f"https://{domain}",
                            is_active=True,
                            excluded_from_search=not is_category_hit,
                            is_category_only=is_category_hit,
                        )
                        db.add(new_comp)
                        if is_category_hit:
                            logger.info("[WEB-SCAN] Category competitor recorded: %s", domain)
                        else:
                            logger.info("[WEB-SCAN] No match on %s — recorded as excluded", domain)
                            skip_domains.add(domain)
                    _url_status = 'category' if is_category_hit else 'no_match'

                else:
                    # Product match found — upsert competitor record
                    competitor = db.query(Competitor).filter(Competitor.domain == domain).first()
                    if competitor is None:
                        competitor = Competitor(
                            domain=domain, name=domain, base_url=f"https://{domain}", is_active=True,
                        )
                        db.add(competitor)
                        db.flush()
                        logger.info("[WEB-SCAN] Auto-created competitor: %s", domain)
                    elif competitor.is_category_only:
                        # Upgrade from category-only to direct competitor
                        competitor.is_category_only = False
                        logger.info("[WEB-SCAN] Upgraded %s from category to direct competitor", domain)

                    competitor_id = competitor.id

                    existing = (
                        db.query(CompetitorProductMatch)
                        .filter(
                            CompetitorProductMatch.master_product_id == result.master_product_id,
                            CompetitorProductMatch.competitor_id == competitor_id,
                            CompetitorProductMatch.competitor_url == url,
                        )
                        .first()
                    )

                    price = page_data.get('price')
                    in_stock = page_data.get('in_stock', True)
                    price_str = f"${price:.2f}" if price else "no price"

                    if existing:
                        if price and existing.competitor_price != price:
                            logger.info("[WEB-SCAN] Price update  domain=%s  product=%r  price=%s", domain, snap['title'], price_str)
                            existing.competitor_price = price
                            existing.scanned_at = datetime.utcnow()
                            db.add(PriceHistory(match_id=existing.id, price=price, in_stock=in_stock))
                        else:
                            logger.debug("[WEB-SCAN] Match already stored  domain=%s  product=%r", domain, snap['title'])
                    else:
                        logger.info("[WEB-SCAN] Match found  domain=%s  product=%r  price=%s  confidence=%d%%",
                                    domain, snap['title'], price_str, int(result.confidence or 0))
                        match = CompetitorProductMatch(
                            master_product_id=result.master_product_id,
                            competitor_id=competitor_id,
                            competitor_url=url,
                            competitor_title=page_data.get('title', '')[:500],
                            competitor_price=price,
                            match_type='|'.join(result.match_types),
                            match_confidence=result.confidence,
                            match_reasons_json=json.dumps(result.reasons),
                            in_stock=in_stock,
                            is_similar=result.is_similar,
                            similarity_reason=result.similarity_reason,
                            scanned_at=datetime.utcnow(),
                        )
                        db.add(match)
                        db.flush()
                        if price:
                            db.add(PriceHistory(match_id=match.id, price=price, in_stock=in_stock))

                    total_matches_count = (
                        db.query(CompetitorProductMatch)
                        .filter(
                            CompetitorProductMatch.competitor_id == competitor_id,
                            CompetitorProductMatch.is_active == True,
                        )
                        .count()
                    )
                    competitor.total_matching_products = total_matches_count
                    competitor.last_scanned_at = datetime.utcnow()
                    if not competitor.first_scanned_at:
                        competitor.first_scanned_at = datetime.utcnow()
                    competitor.scan_session_name = session_name

                    matches += 1
                    _url_status = 'match'

            await _log(_url_status)

        # Visit all URLs for this product concurrently
        await asyncio.gather(*[visit_url(item) for item in search_results])

        return urls_visited, matches

    # Process products one at a time — DDG rate-limits aggressively under concurrent load
    search_sem_outer = asyncio.Semaphore(1)
    checkpoint_emitted = False

    async def bounded_process(snap: dict) -> None:
        nonlocal checkpoint_emitted, total_urls_visited, total_matches
        if _stop_requested:
            return
        async with search_sem_outer:
            if _stop_requested:
                return
            visited, found = await process_product(snap)
            total_urls_visited += visited
            total_matches += found
            await emit('web_search_product_done', {
                'product_id': snap['id'],
                'product_title': snap['title'],
                'urls_visited': visited,
                'matches_found': found,
            })
            # Emit a checkpoint after _CHECKPOINT_THRESHOLD total URLs so the UI can
            # offer the user a chance to stop. The scan continues automatically.
            if not checkpoint_emitted and total_urls_visited >= _CHECKPOINT_THRESHOLD:
                checkpoint_emitted = True
                await emit('web_search_scan_checkpoint', {
                    'total_urls_visited': total_urls_visited,
                    'total_matches': total_matches,
                    'session_name': session_name,
                })
            if not _stop_requested:
                await asyncio.sleep(2)

    await asyncio.gather(*[bounded_process(snap) for snap in product_snapshots])

    # Recount totals from DB
    with session_scope() as db:
        from sqlalchemy import func as sqlfunc
        result_row = (
            db.query(sqlfunc.count(CompetitorProductMatch.id))
            .filter(CompetitorProductMatch.is_active == True)
            .scalar()
        )
        db_total_matches = result_row or 0

    summary = {
        'session_name': session_name,
        'total_products': total_products,
        'total_matches_in_db': db_total_matches,
    }
    logger.info("[WEB-SCAN] Complete: %d products processed", total_products)
    await emit('web_search_scan_complete', summary)
    return summary
