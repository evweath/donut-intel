"""
Per-product sequential competitor search.
Searches for a product, then visits result URLs one at a time (skipping already-seen
domains) until the desired number of competitor matches are found.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import sqlalchemy.exc

from backend.competitor.matcher import MatchCriteria, match_competitor_product, match_similar_product
from backend.database.db import session_scope
from backend.database.models import (
    Competitor,
    CompetitorProductMatch,
    CompetitorScrapingProfile,
    PriceHistory,
    Product,
)
from backend.search.core.fetch import _curl_get, check_internet_reachable
from backend.search.core.parse import (
    _domain,
    _extract_price_float as _extract_price,
    _parse_jsonld,
    _parse_meta,
)
from backend.search.core.constants import narrow_engines
from backend.search.core.rank import multi_engine_search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-run control state for the UI-triggered sequential search
# ---------------------------------------------------------------------------

_comp_search_control: Dict[str, Any] = {
    'stopped': False,
    'resume_event': None,  # asyncio.Event, set by resume or stop signal
}

# How long a pause prompt waits for the user before auto-stopping the search
# and storing whatever has been found so far (seconds).
PAUSE_TIMEOUT_SECONDS = 120


def resume_product_comp_search() -> bool:
    ev = _comp_search_control.get('resume_event')
    if ev:
        ev.set()
        return True
    return False


def stop_product_comp_search() -> bool:
    _comp_search_control['stopped'] = True
    ev = _comp_search_control.get('resume_event')
    if ev:
        ev.set()
    return True


async def _db_write_with_retry(fn, retries: int = 4, base_delay: float = 3.0):
    """Run fn() inside session_scope(), retrying on SQLite 'database is locked'."""
    for attempt in range(retries):
        try:
            with session_scope() as db:
                return fn(db)
        except sqlalchemy.exc.OperationalError as exc:
            if 'database is locked' not in str(exc).lower() or attempt == retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning('[PROD-SEARCH] DB locked, retry %d/%d in %.0fs', attempt + 1, retries, delay)
            await asyncio.sleep(delay)

# Heuristic product-type extraction. The category columns in the DB are
# all NULL (no AI categorization has run), so the "product type" signal
# for the search query is derived from canonical_title via this keyword
# list. Multi-word phrases are listed before single-word catch-alls so
# the longest match wins.
_PRODUCT_TYPE_KEYWORDS = [
    # Donut-specific equipment
    "donut fryer", "donut glazer", "donut depositor", "donut filler", "donut hopper",
    "donut maker", "donut machine", "donut sheeter", "donut cutter", "donut roller",
    "donut robot", "icing machine", "glazing machine", "production sheeter",
    # Mixing / dough
    "spiral mixer", "planetary mixer", "stand mixer", "dough mixer", "dough sheeter",
    "dough divider", "dough rounder", "dough cutter", "dough roller", "rotary cutter",
    # Ovens & baking
    "convection oven", "rotary oven", "rack oven", "deck oven", "pizza oven",
    "conveyor oven", "combi oven",
    # Proofing
    "retarder proofer", "proofing cabinet", "proofer", "retarder",
    # Frying
    "deep fryer", "fryer",
    # Refrigeration
    "walk-in cooler", "walk-in freezer", "reach-in cooler", "reach-in freezer",
    "display case", "merchandiser", "freezer", "refrigerator", "cooler",
    # Holding / warming
    "holding cabinet", "warmer", "heated cabinet",
    # Tables / surfaces
    "feed table", "production table", "work table", "prep table",
    # Ventilation
    "exhaust hood", "ventilation hood", "hood",
    # Smallwares / parts
    "shelving", "scale", "sink", "cart", "rack", "shelf", "screen", "tray", "pan",
    # Ingredients
    "icing", "frosting", "glaze", "filling", "shortening", "syrup", "mix",
    # Generic catch-alls (last resort)
    "sheeter", "cutter", "roller", "robot", "depositor",
    "oven", "mixer", "hopper", "machine", "table",
]


def _extract_product_type(title: Optional[str]) -> str:
    """Return the longest keyword from _PRODUCT_TYPE_KEYWORDS found in *title*, else ''."""
    if not title:
        return ""
    lowered = title.lower()
    for kw in _PRODUCT_TYPE_KEYWORDS:
        if kw in lowered:
            return kw
    return ""


async def _curl_fetch(url: str, timeout: int = 15) -> str:
    """Page fetch — routes through the shared core fetch primitive (core/fetch.py)."""
    return await _curl_get(url, timeout=timeout)


_GENERIC_MANUFACTURERS: frozenset = frozenset({
    'multiple vendors', 'various', 'generic', 'n/a', 'unknown', 'assorted',
})


def _clean_title_for_search(title: str) -> str:
    # Remove everything inside parentheses: (00799579), (APPROX- 226 DOZEN/HR), (4), etc.
    title = re.sub(r'\([^)]*\)', '', title)
    # Compound voltage/frequency specs with V suffix: 208-240v/60/3-ph, 480V/60Hz/3Ph, 208v
    title = re.sub(r'\b\d+[-/]?\d*\s*[Vv]\b(?:[-/]\d+[\w-]*)*', '', title)
    # Standalone electrical tokens: 60Hz, 3ph, 3-phase, 1-Ph, 5kW
    # NOTE: no trailing [\w/-]* — that greedily ate "/1" from "60Hz/1 Ph", orphaning "Ph"
    title = re.sub(r'\b\d+\s*[-]?\s*(?:hz|ph|phase|kw|kva)\b', '', title, flags=re.I)
    # Slash-paired voltage ranges left behind after unit removal: 208/240, 400/480
    title = re.sub(r'\b\d{2,}/\d{2,}\b', '', title)
    # Leading size/package codes: "Small 5.1 ", "3.1-"
    title = re.sub(r'^(?:Small|Medium|Large)?\s*\d+\.\d+[-\s]', '', title, flags=re.I)
    # Standalone part numbers (all-caps/digits with dashes, 6+ chars)
    title = re.sub(r'\b[A-Z0-9]{2,}-[A-Z0-9\-]{3,}\b', '', title)
    # Leftover punctuation noise
    title = re.sub(r'[,;:/]', ' ', title)
    title = re.sub(r'(?<!\w)-|-(?!\w)', ' ', title)
    title = ' '.join(title.split())
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


def _build_query(product: Any, override: Optional[str]) -> str:
    """Build a competitor-search query string from a product.

    Strategy:
      * Anchor on the strongest identifier available — quoted model_number,
        else manufacturer, else cleaned title tokens.
      * Always include a cleaned slice of the title (specs/voltage stripped).
      * Append the heuristically-extracted product_type unless the same
        word(s) are already present in the title — duplicating hurts
        precision more than it helps recall.
    """
    if override:
        return override

    # Prefer the user-curated search term as the query basis; fall back to title.
    title_raw = (getattr(product, 'product_search_term', None) or product.canonical_title or '')
    cleaned_title = _clean_title_for_search(title_raw)
    mfg = (product.manufacturer or '').strip()
    model = product.model_number
    product_type = _extract_product_type(title_raw)

    parts: List[str] = []
    # Treat all-digit "model numbers" of 12+ chars as UPC barcodes — quoting
    # them as an exact-match phrase in a web search is poison (no competitor
    # site lists products by foreign-vendor UPC, so the SERP collapses to 0).
    clean_model = re.sub(r'[^\w\-]', '', model) if model else ''
    looks_like_upc = clean_model.isdigit() and len(clean_model) >= 12
    use_model = bool(clean_model) and not looks_like_upc

    if mfg.lower() in _GENERIC_MANUFACTURERS:
        mfg = ''
    # Consider manufacturer "in title" if its full phrase OR any significant word appears
    mfg_in_title = bool(mfg) and (
        mfg.lower() in cleaned_title.lower()
        or any(w.lower() in cleaned_title.lower() for w in mfg.split() if len(w) > 3)
    )
    if mfg_in_title:
        # Strip full phrase then individual words so "BELSHAW" is removed when
        # mfg is "Belshaw Adamatic" and only "BELSHAW" appears in the title
        cleaned_title = re.sub(r'(?i)\b' + re.escape(mfg) + r'\b', '', cleaned_title)
        for word in mfg.split():
            if len(word) > 3:
                cleaned_title = re.sub(r'(?i)\b' + re.escape(word) + r'\b', '', cleaned_title)
        cleaned_title = ' '.join(cleaned_title.split())

    if use_model:
        if mfg:
            parts.append(mfg)
        parts.append(f'"{clean_model}"')
        # Carry the cleaned title minus the model (the cleaner already
        # strips alnum-dash codes, but be defensive in case the model is
        # plain digits like "5001").
        rest = re.sub(re.escape(clean_model), '', cleaned_title, flags=re.I).strip()
        if rest:
            parts.append(rest)
    elif getattr(product, 'sku', None):
        # No model number — use SKU as keywords (unquoted; quoted multi-hyphen
        # SKUs return near-zero results from all search engines).
        sku = re.sub(r'[^\w\-]', '', product.sku)
        if mfg:
            parts.append(mfg)
        parts.append(sku)
    else:
        if mfg:
            parts.append(mfg)
        if cleaned_title:
            parts.append(cleaned_title)

    if product_type:
        haystack = ' '.join(parts).lower()
        if product_type.lower() not in haystack:
            parts.append(product_type)

    parts.append('buy')
    return ' '.join(p for p in parts if p)


def _get_source_domains() -> set:
    try:
        from backend.config import config
        sites = config.get('source_sites') or []
        return {s['domain'] for s in sites if s.get('domain')}
    except Exception:
        return {'donut-supplies.com', 'donut-equipment.com', 'bakerywholesalers.com'}


class _P:
    """Lightweight product proxy from a snapshot dict."""
    def __init__(self, s: dict) -> None:
        self.__dict__.update(s)
        self.canonical_title = s['title']
        self.product_search_term = s.get('search_term')
        self.price_canonical = s['price']


def _snapshot_product(p: Product) -> dict:
    return {
        'id': p.id,
        'title': p.canonical_title,
        'search_term': p.product_search_term,
        'manufacturer': p.manufacturer,
        'model_number': p.model_number,
        'sku': p.sku,
        'price': p.price_canonical,
        'category': p.category,
    }


def _get_known_competitor_urls(product_id: int) -> List[str]:
    """Return URLs of competitors that previously matched this product, newest first.

    These get injected at the front of the URL queue so existing competitors are
    re-checked before spending time on fresh web searches.
    """
    with session_scope() as db:
        rows = (
            db.query(CompetitorProductMatch.competitor_url, CompetitorProductMatch.scanned_at)
            .filter(
                CompetitorProductMatch.master_product_id == product_id,
                CompetitorProductMatch.is_active == True,
                CompetitorProductMatch.competitor_url.isnot(None),
            )
            .order_by(CompetitorProductMatch.scanned_at.desc())
            .all()
        )
    return [r[0] for r in rows if r[0]]


async def _process_one_product(
    snap: dict,
    criteria: MatchCriteria,
    source_domains: set,
    max_competitors: int,
    max_urls: int = 150,
    num_fetchers: int = 4,
    pause_after: int = 100,
    enable_pause: bool = False,
    pause_at_target: bool = False,
    emit: Callable = None,
    search_query_override: Optional[str] = None,
    log_prefix: str = '[PROD-SEARCH]',
    selected_engines: Optional[set] = None,
) -> int:
    """Search for competitor listings of one product, looping through multiple query
    rounds until *max_competitors* matches are found.

    Each round runs a different query against Google/Bing/Yahoo Shopping plus organic
    engines. *num_fetchers* concurrent HTTP workers are used per round. After every
    *pause_after* unique domains visited without reaching the target, the UI is
    notified so the user can choose to continue or stop.
    """
    query_str = _build_query(_P(snap), search_query_override)
    model = snap.get('model_number', '')
    manufacturer = snap.get('manufacturer', '')
    product_type = _extract_product_type(snap['title'])
    clean_model = re.sub(r'[^\w\-]', '', model) if model else ''
    looks_like_upc = clean_model.isdigit() and len(clean_model) >= 12

    logger.info('%s ── Product: %r  (id=%d)', log_prefix, snap['title'], snap['id'])
    logger.info('%s    Query:   %r', log_prefix, query_str)

    await emit('product_comp_search_progress', {
        'product_id': snap['id'], 'product_title': snap['title'],
        'phase': 'searching', 'found': 0, 'max': max_competitors,
    })

    # Build an ordered list of (query, engines) search rounds.
    # Shopping engines come first in every round; organic fills gaps.
    shopping_engines = ['shopping', 'bing_shopping', 'yahoo_shopping']
    rounds: List[tuple] = []
    rounds.append((query_str, None))  # all engines (shopping first by default)
    if clean_model and not looks_like_upc:
        rounds.append((f'"{clean_model}" buy', shopping_engines + ['bing', 'google']))
        rounds.append((f'"{clean_model}" price compare', shopping_engines + ['bing', 'google', 'ddg']))
    if manufacturer and product_type:
        rounds.append((f'{manufacturer} {product_type} buy', shopping_engines + ['bing', 'google']))
    if product_type:
        rounds.append((f'commercial {product_type} buy price', shopping_engines))
    rounds.append((f'{query_str} alternatives where to buy', shopping_engines + ['bing', 'google', 'ddg']))

    # Pre-load known competitor URLs so they're checked before any web search
    prior_urls = _get_known_competitor_urls(snap['id'])
    if prior_urls:
        logger.info('%s    Pre-queuing %d known competitor URLs', log_prefix, len(prior_urls))

    # Shared mutable state
    found_count = 0
    visited_domains: set = set()
    all_seen_urls: set = set()
    lock = asyncio.Lock()
    fetch_sem = asyncio.Semaphore(num_fetchers)
    last_pause_at = 0  # visited count at last pause checkpoint

    # ------------------------------------------------------------------ #
    # Inner URL processor (shared across all rounds)                       #
    # ------------------------------------------------------------------ #
    async def _process_url(item: dict) -> None:
        nonlocal found_count

        url = item.get('href') or item.get('url', '')
        if not url:
            return
        domain = _domain(url)
        if not domain or domain in source_domains:
            return

        async with lock:
            if domain in visited_domains or found_count >= max_competitors or _comp_search_control['stopped']:
                return
            visited_domains.add(domain)

        await emit('product_comp_search_progress', {
            'product_id': snap['id'], 'product_title': snap['title'],
            'phase': 'visiting', 'current_url': url, 'current_domain': domain,
            'found': found_count, 'max': max_competitors,
        })

        async with fetch_sem:
            html = await _curl_fetch(url)

        if not html:
            logger.debug('%s       Fetch failed — %s', log_prefix, domain)
            return

        page_data = _parse_jsonld(html) or _parse_meta(html)
        if not page_data:
            page_data = {
                'title': item.get('title', ''), 'price': _extract_price(item.get('body', '')),
                'model_number': None, 'manufacturer': None, 'sku': None,
                'in_stock': True, 'image': None, 'description': item.get('body', '') or None,
            }
        else:
            page_data.setdefault('in_stock', True)
            page_data.setdefault('image', None)
            page_data.setdefault('description', None)

        raw_mfr = page_data.get('manufacturer')
        if isinstance(raw_mfr, list):
            raw_mfr = raw_mfr[0] if raw_mfr else None
        if isinstance(raw_mfr, dict):
            raw_mfr = raw_mfr.get('name') or raw_mfr.get('@value') or None
        comp_dict = {
            'title': page_data.get('title', ''), 'price': page_data.get('price'),
            'model_number': page_data.get('model_number'),
            'manufacturer': raw_mfr if isinstance(raw_mfr, str) else None,
            'sku': page_data.get('sku'),
            'description': page_data.get('description', '') or item.get('body', ''),
            'image_hash': None,
        }

        def _do_db_work(db):
            master_products = db.query(Product).filter(Product.is_active == True).all()
            result = match_competitor_product(comp_dict, master_products, criteria)
            if result is None:
                result = match_similar_product(comp_dict, master_products)
            if result is None:
                logger.debug('[PROD-SEARCH]       No match  (page title: %r)', comp_dict.get('title', '')[:60])
                return False

            competitor = db.query(Competitor).filter(Competitor.domain == domain).first()
            if competitor is None:
                competitor = Competitor(
                    domain=domain, name=domain, base_url=f'https://{domain}', is_active=True,
                )
                db.add(competitor)
                db.flush()
                logger.info('[PROD-SEARCH]       Auto-created competitor: %s', domain)

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
            image_url = page_data.get('image')
            price_str = f'${price:.2f}' if price else 'no price'

            if existing:
                if price and existing.competitor_price != price:
                    logger.info('[PROD-SEARCH]       Price update  domain=%s  %s → %s', domain, existing.competitor_price, price_str)
                    existing.competitor_price = price
                    existing.scanned_at = datetime.utcnow()
                    db.add(PriceHistory(match_id=existing.id, price=price, in_stock=in_stock))
                else:
                    logger.debug('[PROD-SEARCH]       Already stored  domain=%s', domain)
            else:
                logger.info('[PROD-SEARCH]       MATCH  domain=%s  price=%s  confidence=%d%%', domain, price_str, int(result.confidence or 0))
                try:
                    from backend.search import searchlog
                    searchlog.record_match(domain, confidence=result.confidence, product_title=snap['title'])
                except Exception:
                    pass
                match = CompetitorProductMatch(
                    master_product_id=result.master_product_id,
                    competitor_id=competitor_id,
                    competitor_url=url,
                    competitor_title=page_data.get('title', '')[:500],
                    competitor_price=price,
                    competitor_image_url=(image_url or '')[:2000] or None,
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

            total_matching = (
                db.query(CompetitorProductMatch)
                .filter(CompetitorProductMatch.competitor_id == competitor_id, CompetitorProductMatch.is_active == True)
                .count()
            )
            competitor.total_matching_products = total_matching
            competitor.last_scanned_at = datetime.utcnow()
            if not competitor.first_scanned_at:
                competitor.first_scanned_at = datetime.utcnow()
            return True

        new_match = await _db_write_with_retry(_do_db_work)
        if new_match:
            async with lock:
                found_count += 1
                current_found = found_count
            logger.info('%s       MATCH  domain=%s  found=%d/%d', log_prefix, domain, current_found, max_competitors)
            await emit('product_comp_search_progress', {
                'product_id': snap['id'], 'product_title': snap['title'],
                'phase': 'found', 'found': current_found, 'max': max_competitors,
                'domain': domain, 'url': url, 'price': page_data.get('price'),
            })

    # ------------------------------------------------------------------ #
    # Round 0: flush known-competitor URLs first, before any web search   #
    # ------------------------------------------------------------------ #
    if prior_urls and found_count < max_competitors:
        prior_items = [{'url': u, 'href': u} for u in prior_urls]
        all_seen_urls.update(prior_urls)   # prevent re-queuing from search results
        logger.info('%s    Checking %d prior competitor URLs', log_prefix, len(prior_items))
        await asyncio.gather(*[_process_url(r) for r in prior_items], return_exceptions=True)

    # Emit a pause prompt and wait (up to PAUSE_TIMEOUT_SECONDS) for the user to
    # choose continue or stop. Returns True to keep searching, False to stop.
    # No response within the timeout is treated as "stop" so a search left
    # unattended finishes and stores its results instead of hanging forever.
    async def _pause_and_wait(reason: str) -> bool:
        resume_ev = asyncio.Event()
        _comp_search_control['resume_event'] = resume_ev
        await emit('product_comp_search_pause', {
            'product_id': snap['id'], 'product_title': snap['title'],
            'reason': reason,
            'found': found_count, 'visited': len(visited_domains),
            'max': max_competitors,
            'timeout': PAUSE_TIMEOUT_SECONDS,
        })
        try:
            await asyncio.wait_for(resume_ev.wait(), timeout=PAUSE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.info('%s    Pause prompt timed out — auto-stopping', log_prefix)
            _comp_search_control['stopped'] = True
        _comp_search_control['resume_event'] = None
        return not _comp_search_control['stopped']

    # ------------------------------------------------------------------ #
    # Main round loop — keeps going until target met or all rounds done   #
    # ------------------------------------------------------------------ #
    round_idx = 0
    while round_idx < len(rounds):
        if _comp_search_control['stopped']:
            break

        # Target reached. If the user explicitly asked for more than the default
        # (pause_at_target is False), just stop here. Otherwise pause and ask
        # whether to search for 10 more.
        if found_count >= max_competitors:
            if not (enable_pause and pause_at_target):
                break
            if not await _pause_and_wait('target_reached'):
                break
            max_competitors += 10  # user chose to keep searching

        round_query, round_engines = rounds[round_idx]
        round_idx += 1

        await emit('product_comp_search_progress', {
            'product_id': snap['id'], 'product_title': snap['title'],
            'phase': 'searching', 'found': found_count, 'max': max_competitors,
        })

        # Narrow this round's engines by the user's selection. round_engines None
        # means "all"; an empty result means the user deselected every engine this
        # round would use, so skip the round entirely.
        effective_engines = narrow_engines(round_engines, selected_engines)
        if selected_engines is not None and not effective_engines:
            continue

        kwargs: Dict[str, Any] = {'query': round_query, 'max_results': 60, 'exclude_domains': source_domains,
                                  'match_pct': 30, 'log_label': f"competitor · {snap['title'][:32]}"}
        if effective_engines:
            kwargs['engines'] = effective_engines
        raw_results = await multi_engine_search(**kwargs)

        # Keep only URLs not seen in previous rounds
        new_items = []
        for r in raw_results:
            url = r.get('href') or r.get('url', '')
            if url and url not in all_seen_urls:
                all_seen_urls.add(url)
                new_items.append(r)

        logger.info('%s    Round %d %r: %d new URLs', log_prefix, round_idx, round_query[:40], len(new_items))

        if not new_items:
            continue

        # Process this round's URLs with num_fetchers concurrent workers
        await asyncio.gather(*[_process_url(r) for r in new_items], return_exceptions=True)

        total_visited = len(visited_domains)

        if _comp_search_control['stopped']:
            break

        # After every pause_after unique domains visited, check in with the user
        if enable_pause and total_visited >= last_pause_at + pause_after and found_count < max_competitors:
            last_pause_at = total_visited
            if not await _pause_and_wait('sites_visited'):
                break
            # User said continue — resume the round loop

    visited_count = len(visited_domains)
    logger.info(
        '%s ── Done: product=%r  visited=%d  found=%d/%d',
        log_prefix, snap['title'], visited_count, found_count, max_competitors,
    )
    await emit('product_comp_search_product_done', {
        'product_id': snap['id'], 'product_title': snap['title'],
        'found': found_count, 'visited': visited_count,
    })
    return found_count


# ---------------------------------------------------------------------------
# Sequential top-level entry (existing API)
# ---------------------------------------------------------------------------

async def run_product_competitor_search(
    product_ids: List[int],
    search_query: Optional[str] = None,
    max_competitors: int = 10,
    max_urls: int = 150,
    num_fetchers: int = 4,
    pause_after: int = 100,
    callbacks: Optional[List[Callable]] = None,
    selected_engines: Optional[set] = None,
) -> dict:
    """Sequential per-product competitor search (one product at a time).

    Processes each product with *num_fetchers* concurrent HTTP workers. After
    exhausting the initial URL pool, emits a pause event so the UI can prompt
    the user to continue or stop.
    """
    _comp_search_control['stopped'] = False
    _comp_search_control['resume_event'] = None

    cbs = callbacks or []
    source_domains = _get_source_domains()
    criteria = MatchCriteria()
    total_found = 0

    async def emit(event: str, data: dict) -> None:
        for cb in cbs:
            try:
                await cb(event, data)
            except Exception:
                pass

    with session_scope() as db:
        products = db.query(Product).filter(
            Product.is_active == True,
            Product.id.in_(product_ids),
        ).all()
        snaps = [_snapshot_product(p) for p in products]

    await emit('product_comp_search_start', {
        'total_products': len(snaps),
        'max_competitors': max_competitors,
    })

    # When the user hasn't asked for more than the default 10 competitors, pause
    # at the target and ask whether to keep going (saves search tokens). If they
    # explicitly requested more, run straight to that target with no prompt.
    pause_at_target = max_competitors <= 10

    for snap in snaps:
        if _comp_search_control['stopped']:
            break
        total_found += await _process_one_product(
            snap=snap,
            criteria=criteria,
            source_domains=source_domains,
            max_competitors=max_competitors,
            max_urls=max_urls,
            num_fetchers=num_fetchers,
            pause_after=pause_after,
            enable_pause=True,
            pause_at_target=pause_at_target,
            emit=emit,
            search_query_override=search_query,
            selected_engines=selected_engines,
        )

    # Found nothing? Distinguish "no competitors exist" from "couldn't reach the
    # internet" (the network on this deployment flaps), so the UI can say which.
    network_ok = True if total_found > 0 else await check_internet_reachable()
    return {'product_ids': product_ids, 'total_found': total_found, 'network_ok': network_ok}


# ---------------------------------------------------------------------------
# Parallel top-level entry (new — 4-worker queue + 5-minute DB refresh)
# ---------------------------------------------------------------------------

# Module-level handle so the API can query / cancel the running scan.
_parallel_state: Dict[str, Any] = {
    'task': None,         # asyncio.Task or None
    'progress': None,     # dict, updated in place by workers
    'started_at': None,   # datetime
}


def get_parallel_search_state() -> dict:
    """Snapshot of the currently-running parallel scan (or empty dict if idle)."""
    task = _parallel_state.get('task')
    if task is None or task.done():
        return {'running': False}
    return {
        'running': True,
        'started_at': _parallel_state['started_at'].isoformat() if _parallel_state['started_at'] else None,
        'progress': dict(_parallel_state['progress'] or {}),
    }


def cancel_parallel_search() -> bool:
    task = _parallel_state.get('task')
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def run_parallel_product_competitor_search(
    num_workers: int = 4,
    sync_interval_seconds: int = 300,
    max_competitors: int = 10,
    max_urls: int = 50,
    product_ids: Optional[List[int]] = None,
    callbacks: Optional[List[Callable]] = None,
    selected_engines: Optional[set] = None,
) -> dict:
    """Run competitor search across many products with a worker pool.

    Spawns *num_workers* async worker tasks that pull product IDs from a
    shared queue. Every *sync_interval_seconds* a refresher re-queries
    active products and enqueues any that weren't there at start (or were
    added since). The scan runs until externally cancelled or until the
    queue is drained and no new products show up in two refresh cycles.
    """
    # Reset the sequential-search stop flag so prior stopped runs don't
    # silently skip every URL inside _process_one_product.
    _comp_search_control['stopped'] = False

    cbs = callbacks or []
    source_domains = _get_source_domains()
    criteria = MatchCriteria()

    async def emit(event: str, data: dict) -> None:
        for cb in cbs:
            try:
                await cb(event, data)
            except Exception:
                pass

    queue: asyncio.Queue = asyncio.Queue()
    processed_ids: set = set()
    in_flight_ids: set = set()
    progress: Dict[str, Any] = {
        'total_queued': 0,
        'processed': 0,
        'total_found': 0,
        'workers_active': 0,
        'num_workers': num_workers,
        'sync_interval_seconds': sync_interval_seconds,
        'last_refresh_at': None,
        'started_at': datetime.utcnow().isoformat(),
    }
    _parallel_state['progress'] = progress
    _parallel_state['started_at'] = datetime.utcnow()

    def _load_target_snapshots() -> List[dict]:
        with session_scope() as db:
            q = db.query(Product).filter(Product.is_active == True)
            if product_ids:
                q = q.filter(Product.id.in_(product_ids))
            return [_snapshot_product(p) for p in q.all()]

    def _enqueue_new(snaps: List[dict]) -> int:
        added = 0
        for s in snaps:
            if s['id'] in processed_ids or s['id'] in in_flight_ids:
                continue
            in_flight_ids.add(s['id'])
            queue.put_nowait(s)
            progress['total_queued'] += 1
            added += 1
        return added

    # Initial load
    initial = _load_target_snapshots()
    added = _enqueue_new(initial)
    logger.info(
        "[PARALLEL-SEARCH] Starting: %d products queued, %d workers, sync_interval=%ds",
        added, num_workers, sync_interval_seconds,
    )
    await emit('parallel_search_start', {
        'total_products': added,
        'num_workers': num_workers,
        'sync_interval_seconds': sync_interval_seconds,
        'max_competitors': max_competitors,
    })

    async def worker(worker_id: int) -> None:
        prefix = f"[PARALLEL-SEARCH][w{worker_id}]"
        while True:
            snap = await queue.get()
            progress['workers_active'] += 1
            try:
                found = await _process_one_product(
                    snap=snap,
                    criteria=criteria,
                    source_domains=source_domains,
                    max_competitors=max_competitors,
                    max_urls=max_urls,
                    emit=emit,
                    log_prefix=prefix,
                    selected_engines=selected_engines,
                )
                progress['total_found'] += found
                processed_ids.add(snap['id'])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("%s failed on product id=%d: %s", prefix, snap['id'], exc)
            finally:
                in_flight_ids.discard(snap['id'])
                progress['processed'] += 1
                progress['workers_active'] -= 1
                queue.task_done()
                await emit('parallel_search_progress', {
                    'worker_id': worker_id,
                    'processed': progress['processed'],
                    'total_queued': progress['total_queued'],
                    'remaining': queue.qsize(),
                    'total_found': progress['total_found'],
                    'workers_active': progress['workers_active'],
                })

    async def refresher() -> None:
        while True:
            await asyncio.sleep(sync_interval_seconds)
            try:
                added_n = _enqueue_new(_load_target_snapshots())
                progress['last_refresh_at'] = datetime.utcnow().isoformat()
                if added_n:
                    logger.info(
                        "[PARALLEL-SEARCH] refresh added %d new products (total_queued=%d)",
                        added_n, progress['total_queued'],
                    )
                await emit('parallel_search_refresh', {
                    'new_products': added_n,
                    'total_queued': progress['total_queued'],
                    'processed': progress['processed'],
                    'last_refresh_at': progress['last_refresh_at'],
                })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("[PARALLEL-SEARCH] refresh failed: %s", exc)

    worker_tasks = [asyncio.create_task(worker(i)) for i in range(num_workers)]
    refresh_task = asyncio.create_task(refresher())

    # When searching a fixed product list, the target set is known and finite.
    # Terminate as soon as the queue drains — no refresh cycles needed.
    fixed_product_set = bool(product_ids)

    try:
        if fixed_product_set:
            await queue.join()
        else:
            # All-products mode: drain the queue, then wait one refresh cycle to see
            # if new products show up; bail after two consecutive empty refreshes.
            empty_refreshes = 0
            while True:
                await queue.join()
                queued_before = progress['total_queued']
                await asyncio.sleep(sync_interval_seconds + 1)
                if progress['total_queued'] == queued_before and queue.empty():
                    empty_refreshes += 1
                    if empty_refreshes >= 2:
                        break
                else:
                    empty_refreshes = 0
    except asyncio.CancelledError:
        logger.info("[PARALLEL-SEARCH] cancelled by caller")
        raise
    finally:
        refresh_task.cancel()
        for w in worker_tasks:
            w.cancel()
        await asyncio.gather(*worker_tasks, refresh_task, return_exceptions=True)
        _parallel_state['task'] = None

    network_ok = True if progress['total_found'] > 0 else await check_internet_reachable()
    await emit('parallel_search_complete', {
        'total_processed': progress['processed'],
        'total_found': progress['total_found'],
        'total_queued': progress['total_queued'],
        'network_ok': network_ok,
    })
    logger.info(
        "[PARALLEL-SEARCH] complete: processed=%d total_found=%d network_ok=%s",
        progress['processed'], progress['total_found'], network_ok,
    )

    return {
        'total_processed': progress['processed'],
        'total_found': progress['total_found'],
        'total_queued': progress['total_queued'],
        'network_ok': network_ok,
    }
