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
from urllib.parse import urlparse

import httpx

from backend.competitor.matcher import MatchCriteria, MatchResult, match_competitor_product, match_similar_product
from backend.database.db import session_scope
from backend.database.models import (
    Competitor,
    CompetitorProductMatch,
    CompetitorScrapingProfile,
    PriceHistory,
    Product,
)
from backend.search.engine import multi_engine_search

logger = logging.getLogger(__name__)

COOLDOWN_DAYS = 3
_FETCH_CONCURRENCY = 10  # max concurrent httpx page fetches
_SEARCH_CONCURRENCY = 5  # max concurrent per-product searches

_FETCH_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15'
    ),
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.9',
    'Accept-Language': 'en-US,en;q=0.9',
}

_PRICE_RE = re.compile(r'\$\s*([\d,]+(?:\.\d{1,2})?)')
_MODEL_RE = re.compile(r'(?:model|part|item)[#\s:]+([A-Z0-9][\w\-]{2,})', re.I)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip('www.')
    except Exception:
        return ''


def _build_query(product: Product) -> str:
    """Build a search query that identifies this specific product."""
    parts: List[str] = []
    if product.manufacturer and product.model_number:
        # Quoted model keeps it specific without over-constraining
        parts.append(product.manufacturer)
        parts.append(f'"{product.model_number}"')
    elif product.model_number:
        parts.append(f'"{product.model_number}"')
    else:
        # Unquoted title — more flexible, avoids "no results" on long exact-match queries
        title = (product.canonical_title or '')[:60]
        parts.append(title)
    parts.append('buy')
    return ' '.join(parts)


def _extract_price(text: str) -> Optional[float]:
    m = _PRICE_RE.search(text or '')
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            pass
    return None


def _extract_model(text: str) -> Optional[str]:
    m = _MODEL_RE.search(text or '')
    return m.group(1).strip() if m else None


def _parse_jsonld(html: str) -> Optional[Dict[str, Any]]:
    """Extract the first schema.org/Product from JSON-LD blocks."""
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.I
    ):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and '@graph' in data:
            items = data['@graph']
        for item in items:
            if not isinstance(item, dict):
                continue
            type_val = item.get('@type', '')
            if 'Product' not in (type_val if isinstance(type_val, str) else ' '.join(type_val)):
                continue
            price: Optional[float] = None
            offers = item.get('offers', {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                raw_price = offers.get('price') or offers.get('lowPrice')
                if raw_price is not None:
                    try:
                        price = float(str(raw_price).replace(',', '').replace('$', ''))
                    except ValueError:
                        pass
            brand = item.get('brand', {})
            manufacturer = brand.get('name') if isinstance(brand, dict) else (brand or None)
            in_stock = 'InStock' in json.dumps(item.get('offers', ''))
            return {
                'title': item.get('name', ''),
                'price': price,
                'model_number': item.get('model') or item.get('mpn'),
                'manufacturer': manufacturer,
                'sku': item.get('sku'),
                'in_stock': in_stock,
            }
    return None


def _meta_val(html: str, prop: str) -> Optional[str]:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\'][^"\']*{re.escape(prop)}[^"\']*["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.I
    )
    if m:
        return m.group(1).strip()
    # alternate attribute order
    m = re.search(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'][^"\']*{re.escape(prop)}[^"\']*["\']',
        html, re.I
    )
    return m.group(1).strip() if m else None


def _parse_meta(html: str) -> Dict[str, Any]:
    """Fallback: extract product info from meta / OG / title tags."""
    title_tag = re.search(r'<title[^>]*>([^<]{1,300})</title>', html, re.I)
    title = _meta_val(html, 'og:title') or _meta_val(html, 'title') or (title_tag.group(1).strip() if title_tag else '')

    price_str = (
        _meta_val(html, 'price:amount') or
        _meta_val(html, 'og:price:amount') or
        _meta_val(html, 'product:price:amount') or
        _meta_val(html, 'price')
    )
    price: Optional[float] = None
    if price_str:
        try:
            price = float(re.sub(r'[^\d.]', '', price_str))
        except ValueError:
            pass
    if price is None:
        price = _extract_price(html[:8000])

    return {
        'title': title or '',
        'price': price,
        'model_number': _meta_val(html, 'model') or _meta_val(html, 'mpn'),
        'manufacturer': _meta_val(html, 'og:brand') or _meta_val(html, 'brand'),
        'sku': _meta_val(html, 'sku') or _meta_val(html, 'product:retailer_item_id'),
        'in_stock': True,
    }


async def _fetch_product_data(url: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Fetch a product page and extract structured data. Returns None on failure."""
    try:
        r = await client.get(url, timeout=12, follow_redirects=True)
        if r.status_code not in (200, 206):
            return None
        html = r.text
        data = _parse_jsonld(html) or _parse_meta(html)
        if data:
            data['url'] = str(r.url)
            data['source_site'] = _domain(str(r.url))
        return data
    except Exception as exc:
        logger.debug("Failed to fetch %s: %s", url, exc)
        return None


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
) -> dict:
    """
    Run a full web-search-first scan across the product catalog.

    Args:
        session_name: Label for this scan run.
        max_results: Number of search-result URLs to visit per product (1–100).
        product_ids: Limit to specific product IDs; None = all active products.
        callbacks: List of async (event, data) callables for progress events.
        force: Ignore 3-day cooldown for all competitors.

    Returns:
        Summary dict with total_products, total_urls_visited, total_matches.
    """
    max_results = max(1, min(100, max_results))
    cbs = callbacks or []
    source_domains = _get_source_domains()

    async def emit(event: str, data: dict) -> None:
        for cb in cbs:
            try:
                await cb(event, data)
            except Exception:
                pass

    # --- Load products ---
    with session_scope() as db:
        q = db.query(Product).filter(Product.is_active == True)
        if product_ids:
            q = q.filter(Product.id.in_(product_ids))
        # Order by price descending so the most valuable products are searched first
        q = q.order_by(Product.price_canonical.desc().nullslast())
        if product_limit:
            q = q.limit(product_limit)
        products = q.all()
        # detach — we'll open new sessions per batch
        product_snapshots = [
            {
                'id': p.id,
                'title': p.canonical_title,
                'manufacturer': p.manufacturer,
                'model_number': p.model_number,
                'sku': p.sku,
                'price': p.price_canonical,
                'category': p.category,
            }
            for p in products
        ]

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
                self.manufacturer = s['manufacturer']
                self.model_number = s['model_number']
                self.sku = s['sku']
                self.price_canonical = s['price']
                self.category = s['category']
                self.images = []

        fake = _FakeProduct(snap)

        query = _build_query(fake)

        async with search_sem:
            search_results = await multi_engine_search(
                query=query,
                max_results=max_results,
                exclude_domains=source_domains,
            )

        if not search_results:
            return 0, 0

        urls_visited = 0
        matches = 0

        async with httpx.AsyncClient(headers=_FETCH_HEADERS) as client:
            async def visit_url(item: dict) -> None:
                nonlocal urls_visited, matches
                url = item.get('href') or item.get('url', '')
                if not url:
                    return
                domain = _domain(url)
                if not domain:
                    return

                # Check cooldown for this competitor domain
                with session_scope() as db:
                    competitor = db.query(Competitor).filter(Competitor.domain == domain).first()
                    if competitor and competitor.scraping_profile:
                        if _is_in_cooldown(competitor.scraping_profile, force=force):
                            logger.debug("[WEB-SCAN] Skipping %s (3-day cooldown)", domain)
                            return

                async with fetch_sem:
                    page_data = await _fetch_product_data(url, client)

                urls_visited += 1

                if not page_data or not page_data.get('title'):
                    # Use snippet data as fallback
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

                comp_dict = {
                    'title': page_data.get('title', ''),
                    'price': page_data.get('price'),
                    'model_number': page_data.get('model_number'),
                    'manufacturer': page_data.get('manufacturer'),
                    'sku': page_data.get('sku'),
                    'description': item.get('body', ''),
                    'image_hash': None,
                }

                # Reload all active products for matching (cached in closure scope is unsafe across sessions)
                with session_scope() as db:
                    master_products = db.query(Product).filter(Product.is_active == True).all()
                    result = match_competitor_product(comp_dict, master_products, criteria)
                    if result is None:
                        result = match_similar_product(comp_dict, master_products)
                    if result is None:
                        return

                    # Get or create competitor
                    competitor = db.query(Competitor).filter(Competitor.domain == domain).first()
                    if competitor is None:
                        competitor = Competitor(
                            domain=domain,
                            name=domain,
                            base_url=f"https://{domain}",
                            is_active=True,
                        )
                        db.add(competitor)
                        db.flush()
                        logger.info("[WEB-SCAN] Auto-created competitor: %s", domain)

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

                    if existing:
                        if price and existing.competitor_price != price:
                            existing.competitor_price = price
                            existing.scanned_at = datetime.utcnow()
                            db.add(PriceHistory(match_id=existing.id, price=price, in_stock=in_stock))
                    else:
                        import json as _json
                        match = CompetitorProductMatch(
                            master_product_id=result.master_product_id,
                            competitor_id=competitor_id,
                            competitor_url=url,
                            competitor_title=page_data.get('title', '')[:500],
                            competitor_price=price,
                            match_type='|'.join(result.match_types),
                            match_confidence=result.confidence,
                            match_reasons_json=_json.dumps(result.reasons),
                            in_stock=in_stock,
                            is_similar=result.is_similar,
                            similarity_reason=result.similarity_reason,
                            scanned_at=datetime.utcnow(),
                        )
                        db.add(match)
                        db.flush()
                        if price:
                            db.add(PriceHistory(match_id=match.id, price=price, in_stock=in_stock))

                    # Update competitor stats
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

            # Visit all URLs for this product concurrently
            await asyncio.gather(*[visit_url(item) for item in search_results])

        return urls_visited, matches

    # Process products one at a time — DDG rate-limits aggressively under concurrent load
    search_sem_outer = asyncio.Semaphore(1)

    async def bounded_process(snap: dict) -> None:
        async with search_sem_outer:
            visited, found = await process_product(snap)
            await emit('web_search_product_done', {
                'product_id': snap['id'],
                'product_title': snap['title'],
                'urls_visited': visited,
                'matches_found': found,
            })
            await asyncio.sleep(2)  # brief pause between products to stay under DDG rate limits

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
