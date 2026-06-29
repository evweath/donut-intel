"""
Competitors page — search each known competitor's own website for a target product.

Page-specific orchestration: per-competitor query ordering, fuzzy scoring against
the target, and flattening results across competitors. The site-search mechanics
live in core/engines.py.
"""
import asyncio
from typing import Any, Dict, List, Optional

from backend.search.core.engines import _search_competitor_site
from backend.search.core.rank import fuzzy_score


async def search_competitor_websites(
    product_name: str,
    model_number: Optional[str],
    category: Optional[str],
    competitor_domains: List[str],
    max_results_per_competitor: int = 5,
    min_fuzzy_score: int = 0,
) -> List[Dict[str, Any]]:
    """
    Search each competitor's own site for the target product.

    For each competitor, tries queries in this order:
      1. product_name  (without "buy")
      2. model_number  (if provided)
      3. category      (if provided)

    Each result is scored 0–100 against the target using fuzzy token matching.
    Results below min_fuzzy_score are filtered out.
    Returns a flat list sorted by fuzzy_score descending.
    """
    target = ' '.join(filter(None, [model_number, product_name]))
    queries = list(filter(None, [product_name, model_number, category]))

    # _curl_get is genuinely async (primp AsyncClient), not thread-pool bound, so we
    # can fan out widely. The per-domain timeout below is what actually bounds the
    # search: without it, a few unresponsive domains (10 patterns each) dominate the
    # whole wall-clock. With it, every domain is abandoned after PER_DOMAIN_TIMEOUT.
    CONCURRENCY = 64
    PER_DOMAIN_TIMEOUT = 10  # seconds — hard cap per competitor site
    _sem = asyncio.Semaphore(CONCURRENCY)

    # Live progress so the user can watch the scan run and the match count climb.
    from backend.search import searchlog
    total = len(competitor_domains)
    _progress = {"done": 0, "matches": 0}
    _HEARTBEAT_EVERY = 25
    searchlog.record_note(f'scanning {total} competitor sites for "{product_name}"…')

    async def _probe(domain: str) -> List[Dict[str, Any]]:
        seen_urls: set = set()
        collected: List[Dict] = []
        for query in queries:
            try:
                items = await _search_competitor_site(domain, query, max_results=15)
                for item in items:
                    url = item.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        score = fuzzy_score(
                            item.get('title', ''), item.get('description', ''), target
                        )
                        collected.append({**item, 'fuzzy_score': score, 'source_query': query})
            except Exception:
                pass

        collected.sort(key=lambda x: -x['fuzzy_score'])
        if min_fuzzy_score > 0:
            collected = [x for x in collected if x['fuzzy_score'] >= min_fuzzy_score]
        return collected[:max_results_per_competitor]

    async def _search_one(domain: str) -> List[Dict[str, Any]]:
        async with _sem:
            try:
                hits = await asyncio.wait_for(_probe(domain), timeout=PER_DOMAIN_TIMEOUT)
            except (asyncio.TimeoutError, Exception):
                hits = []
        # Synchronous block (no await) — safe to mutate shared progress state.
        _progress["done"] += 1
        if hits:
            _progress["matches"] += len(hits)
            best = max((h.get("fuzzy_score", 0) for h in hits), default=0)
            searchlog.record_match(domain, confidence=best, product_title=product_name)
        if _progress["done"] % _HEARTBEAT_EVERY == 0 or _progress["done"] == total:
            searchlog.record_note(
                f'scanned {_progress["done"]}/{total} competitor sites — '
                f'{_progress["matches"]} match{"es" if _progress["matches"] != 1 else ""} so far'
            )
        return hits

    raw = await asyncio.gather(*[_search_one(d) for d in competitor_domains],
                               return_exceptions=True)

    flat: List[Dict] = []
    for domain, chunk in zip(competitor_domains, raw):
        if isinstance(chunk, Exception):
            continue
        for item in chunk:
            flat.append({**item, 'competitor_domain': domain})

    flat.sort(key=lambda x: -x.get('fuzzy_score', 0))
    return flat
