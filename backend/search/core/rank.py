"""
Cross-engine aggregation, scoring, and price enrichment.

`multi_engine_search` is the central hub: it fans out to the engine adapters
selected by the caller, then merges and ranks. Page modules call this with their
own engine list rather than touching individual engines.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.search.core.constants import _NOISE_DOMAINS
from backend.search.core.engines import (
    _bing_search,
    _bing_shopping_search,
    _duckduckgo_shopping_search,
    _google_search,
    _google_shopping_search,
    _text_search,
    _yahoo_search,
    _yahoo_shopping_search,
)
from backend.search.core.fetch import _curl_get
from backend.search.core.parse import (
    _domain,
    _extract_model,
    _extract_price,
    _is_homepage,
)

logger = logging.getLogger(__name__)


def fuzzy_score(candidate_title: str, candidate_desc: str, target: str) -> int:
    """Return 0–100 fuzzy match score of a candidate product against the target string."""
    from rapidfuzz import fuzz
    combined = f"{candidate_title} {candidate_desc}".strip()
    if not combined or not target:
        return 0
    return int(fuzz.token_set_ratio(combined.lower(), target.lower()))


async def _enrich_prices(results: List[Dict[str, Any]], concurrency: int = 8) -> List[Dict[str, Any]]:
    """For results that have no price, attempt a lightweight page fetch to find one."""
    sem = asyncio.Semaphore(concurrency)

    async def _try(item: Dict) -> Dict:
        if item.get('price'):
            return item
        async with sem:
            try:
                html = await _curl_get(item['url'], timeout=6)
                if html:
                    price = _extract_price(html[:15000])
                    if price:
                        return {**item, 'price': price}
            except Exception:
                pass
        return item

    enriched = await asyncio.gather(*[_try(r) for r in results], return_exceptions=True)
    return [r if not isinstance(r, Exception) else orig
            for r, orig in zip(enriched, results)]


async def multi_engine_search(
    query: str,
    max_results: int = 20,
    exclude_domains: Optional[set] = None,
    engines: Optional[List[str]] = None,
    match_pct: Optional[float] = None,
    log_label: str = "",
) -> List[Dict[str, Any]]:
    """
    Search across DuckDuckGo, Bing, Google, Yahoo, and Google Shopping concurrently.

    Google Shopping results are always included first and are URL-deduplicated (so
    multiple products from the same seller are all captured). Organic results from the
    other engines fill remaining slots up to max_results, domain-deduplicated and
    ranked by cross-engine agreement.
    """
    if engines is None:
        engines = ['ddg', 'bing', 'google', 'yahoo', 'shopping', 'bing_shopping', 'yahoo_shopping', 'ddg_shopping']
    exclude = exclude_domains or set()
    fetch = max_results * 3  # over-fetch to account for filtering

    from backend.search import searchlog
    _pct = f" ({round(match_pct)}% match)" if match_pct is not None else ""

    async def _logged(engine_key: str, coro):
        """Emit a live-log line as this engine starts and finishes, so the user
        sees the search is still running and how many hits each engine returned."""
        name = searchlog.engine_names([engine_key])[0]
        searchlog.record_note(f'searching {name} for "{query}"{_pct}')
        try:
            res = await coro
        except Exception:
            searchlog.record_note(f'{name}: no response')
            raise
        searchlog.record_note(f'{name}: {len(res or [])} found')
        return res

    # Build tasks; track which indices are shopping sources.
    tasks: List = []
    shopping_indices: List[int] = []
    if 'ddg' in engines:
        tasks.append(_logged('ddg', _text_search(query, max_results=fetch)))
    if 'bing' in engines:
        tasks.append(_logged('bing', _bing_search(query, max_results=fetch)))
    if 'google' in engines:
        tasks.append(_logged('google', _google_search(query, max_results=fetch)))
    if 'yahoo' in engines:
        tasks.append(_logged('yahoo', _yahoo_search(query, max_results=fetch)))
    if 'shopping' in engines:
        shopping_indices.append(len(tasks))
        tasks.append(_logged('shopping', _google_shopping_search(query, max_results=fetch)))
    if 'bing_shopping' in engines:
        shopping_indices.append(len(tasks))
        tasks.append(_logged('bing_shopping', _bing_shopping_search(query, max_results=fetch)))
    if 'yahoo_shopping' in engines:
        shopping_indices.append(len(tasks))
        tasks.append(_logged('yahoo_shopping', _yahoo_shopping_search(query, max_results=fetch)))
    if 'ddg_shopping' in engines:
        shopping_indices.append(len(tasks))
        tasks.append(_logged('ddg_shopping', _duckduckgo_shopping_search(query, max_results=fetch)))

    raw = await asyncio.gather(*tasks, return_exceptions=True)

    # --- Pass 1: collect all Shopping results (URL-keyed, multiple per domain allowed) ---
    shopping_results: List[Dict[str, Any]] = []
    seen_shopping_urls: set = set()
    for sidx in shopping_indices:
        if isinstance(raw[sidx], Exception):
            continue
        for item in (raw[sidx] or []):
            url = item.get('href', '') or item.get('url', '')
            if not url or _is_homepage(url) or url in seen_shopping_urls:
                continue
            domain = _domain(url)
            if not domain or domain in exclude or domain in _NOISE_DOMAINS:
                continue
            seen_shopping_urls.add(url)
            shopping_results.append({
                'href': url, 'url': url, 'domain': domain,
                'title': item.get('title', ''),
                'body': item.get('body', '') or item.get('description', ''),
                'price': item.get('price'),
            })

    # --- Pass 2: score organic results at domain level, skip URLs already in Shopping ---
    domain_score: Dict[str, int] = {}
    domain_best: Dict[str, Dict] = {}
    organic_indices = [i for i in range(len(tasks)) if i not in shopping_indices]

    for i in organic_indices:
        engine_results = raw[i]
        if isinstance(engine_results, Exception):
            continue
        for item in (engine_results or []):
            url = item.get('href', '') or item.get('url', '')
            if not url or _is_homepage(url) or url in seen_shopping_urls:
                continue
            domain = _domain(url)
            if not domain or domain in exclude or domain in _NOISE_DOMAINS:
                continue
            domain_score[domain] = domain_score.get(domain, 0) + 1
            entry = {
                'href': url, 'url': url, 'domain': domain,
                'title': item.get('title', ''),
                'body': item.get('body', '') or item.get('description', ''),
                'price': item.get('price'),
            }
            cur = domain_best.get(domain)
            if cur is None:
                domain_best[domain] = entry
            else:
                if not cur['title'] and entry['title']:
                    cur['title'] = entry['title']
                if not cur['body'] and entry['body']:
                    cur['body'] = entry['body']
                if not cur['price'] and entry['price']:
                    cur['price'] = entry['price']

    ranked_organic = sorted(domain_score.keys(), key=lambda d: -domain_score[d])
    # Shopping results first (have embedded prices), organic fills remaining slots.
    organic_slots = max(0, max_results - len(shopping_results))
    final = shopping_results + [domain_best[d] for d in ranked_organic[:organic_slots]]

    # Record this search for the Live Search Log panel: % match, term, the
    # engines/websites queried, and the results. Best-effort, never raises.
    from backend.search import searchlog
    searchlog.record_search(query, engines, final, match_pct=match_pct, label=log_label)

    return final


def _aggregate_and_rank(
    all_raw: list,
    img_idx: Dict[str, str],
    max_results: int,
    exclude_fn=None,
) -> List[Dict[str, Any]]:
    """Shared result aggregation for find_products / find_suppliers.

    Merges results from multiple concurrent engine calls, scores by cross-engine
    agreement (shopping results weighted 2×), deduplicates by domain, and returns
    up to max_results enriched result dicts.
    """
    domain_score: Dict[str, int] = {}
    domain_best: Dict[str, Dict] = {}

    for engine_results in all_raw:
        if isinstance(engine_results, Exception):
            continue
        for item in (engine_results or []):
            url = item.get('href', '') or item.get('url', '')
            if not url or _is_homepage(url):
                continue
            domain = _domain(url)
            if not domain or domain in _NOISE_DOMAINS:
                continue
            if exclude_fn and exclude_fn(domain):
                continue
            is_shopping = item.get('source') == 'shopping'
            domain_score[domain] = domain_score.get(domain, 0) + (2 if is_shopping else 1)
            entry = {
                'url': url, 'domain': domain,
                'title': item.get('title', ''),
                'body': item.get('body', '') or item.get('description', ''),
                'price': item.get('price'),
            }
            cur = domain_best.get(domain)
            if cur is None:
                domain_best[domain] = entry
            else:
                if not cur['title'] and entry['title']:
                    cur['title'] = entry['title']
                    cur['url'] = url
                if not cur['body'] and entry['body']:
                    cur['body'] = entry['body']
                if not cur['price'] and entry['price']:
                    cur['price'] = entry['price']

    ranked = sorted(domain_score.keys(), key=lambda d: -domain_score[d])
    out: List[Dict] = []
    for domain in ranked:
        item = domain_best[domain]
        snippet = item.get('body', '') or ''
        out.append({
            'url': item['url'],
            'domain': domain,
            'title': item.get('title', ''),
            'description': snippet,
            'price': item.get('price') or _extract_price(snippet),
            'model_number': _extract_model(snippet),
            'image': img_idx.get(domain, ''),
        })
        if len(out) >= max_results:
            break
    return out
