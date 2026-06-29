"""
Find This Product page — search the web for buyable copies of a specific product.

Page-specific orchestration only: query construction, competitor/own-domain
exclusion, and result shaping. All engine work goes through core/.
"""
import asyncio
from typing import Any, Dict, List, Optional

from backend.search.core.constants import NON_GOOGLE_SHOPPING, narrow_engines
from backend.search.core.engines import _google_shopping_search, _image_search
from backend.search.core.parse import _img_index
from backend.search.core.rank import _aggregate_and_rank, _enrich_prices, multi_engine_search


async def find_products(
    product_name: str,
    model_number: Optional[str] = None,
    category: Optional[str] = None,
    competitor_model_map: Optional[Dict[str, set]] = None,
    exclude_own_domains: Optional[set] = None,
    max_results: int = 5,
    selected_engines: Optional[set] = None,
    exclude_domains: Optional[set] = None,
    match_pct: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Search the web for a product using the search term EXACTLY as given.

    The query is `product_name` verbatim — no "buy" prefix, no model/category
    variants, no other decoration. The caller passes the user-curated product
    search term, and the user controls the entire query through it.

    competitor_model_map: {domain: {model_numbers already tracked}} — a competitor
    domain is excluded only when the specific model_number being searched is already
    present in its tracked set. Pass None to exclude no competitors.

    selected_engines: set of engine keys the user narrowed the search to, or None
    for all engines. The Google Shopping pass runs only when 'shopping' is selected.
    """
    own = exclude_own_domains or set()
    already_found = exclude_domains or set()   # competitors from a prior batch (continue)
    shopping_on = selected_engines is None or 'shopping' in selected_engines

    def _should_exclude(domain: str) -> bool:
        if domain in own or domain in already_found:
            return True
        if model_number and competitor_model_map:
            tracked = competitor_model_map.get(domain, set())
            if any(model_number.lower() == m.lower() for m in tracked):
                return True
        return False

    # Single query — the product search term used VERBATIM. No prefix/suffix and
    # no model/category variants: every search uses exactly the given text.
    query = product_name
    from backend.search import searchlog
    _pct = f" ({round(match_pct)}% match)" if match_pct is not None else ""
    search_tasks: List[Any] = []
    term_engines = narrow_engines(
        ['ddg', 'bing', 'google', 'yahoo', *NON_GOOGLE_SHOPPING], selected_engines)
    if term_engines:
        search_tasks.append(multi_engine_search(
            query, max_results=max_results * 4,
            engines=term_engines, log_label="find product", match_pct=match_pct,
        ))
    if shopping_on:
        # Google Shopping runs outside multi_engine_search, so log its progress here
        # too (it is the slowest of the result sources and the one users watch for).
        async def _logged_shopping():
            name = searchlog.engine_names(['shopping'])[0]
            searchlog.record_note(f'searching {name} for "{query}"{_pct}')
            res = await _google_shopping_search(query, max_results=max_results * 3)
            searchlog.record_note(f'{name}: {len(res or [])} found')
            return res

        search_tasks.append(_logged_shopping())

    all_raw, images = await asyncio.gather(
        asyncio.gather(*search_tasks, return_exceptions=True),
        _image_search(query, max_results=max_results * 2),
    )
    img_idx = _img_index(images) if isinstance(images, list) else {}

    pre_enrich = _aggregate_and_rank(all_raw, img_idx, max_results, exclude_fn=_should_exclude)
    searchlog.record_note(f'found {len(pre_enrich)} web products — fetching prices…')
    return await _enrich_prices(pre_enrich)
