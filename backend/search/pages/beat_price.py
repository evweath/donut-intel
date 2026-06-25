"""
Beat This Price page — find alternate suppliers/wholesalers for a product.

Page-specific orchestration: pattern-query fan-out, fuzzy scoring against the
original description, the price carry-over dedup, and the 30%-floor fallback.

NOTE: the engine list at the multi_engine_search call below MUST include
'shopping' and 'bing_shopping'. Organic engines never return structured prices —
omitting the shopping engines is what broke price display for multiple sessions.
See .claude/investigations/beat-this-price.md.
"""
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from backend.search.core.constants import narrow_engines
from backend.search.core.engines import _google_shopping_search, _image_search
from backend.search.core.parse import _img_index
from backend.search.core.rank import (
    _aggregate_and_rank,
    _enrich_prices,
    fuzzy_score,
    multi_engine_search,
)


async def find_suppliers(
    description: str,
    model_number: Optional[str] = None,
    category: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    characteristics: Optional[Dict] = None,
    max_results: int = 10,
    pattern_queries: Optional[List[Tuple[str, str]]] = None,
    selected_engines: Optional[set] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Find alternate suppliers using pattern-based title queries.

    pattern_queries is an ordered list of (pattern_id, query_text) produced by
    pattern_learner.generate_queries().  Each pattern runs its own concurrent
    search; all results are fuzzy-scored against the original description,
    deduplicated by domain, sorted best-first.  Results with fuzzy score >=30%
    are preferred; if fewer than 3 clear that bar the top results are returned
    regardless so the page is never empty.

    Returns (results, per_pattern_best_fuzzy) where per_pattern_best_fuzzy maps
    each pattern_id to the highest fuzzy score any of its results achieved.
    """
    char_parts: List[str] = [str(v) for v in (characteristics or {}).values() if v]
    price_hint = f"under ${price_max:.0f}" if price_max else (f"over ${price_min:.0f}" if price_min else '')

    if not pattern_queries:
        pattern_queries = [("full", description)]

    # Narrow each query's engine list by the user's selection (None = all). The
    # pattern query carries every shopping surface so all are reachable from the
    # page's checkboxes.
    # NOTE: the default list MUST keep 'shopping' and 'bing_shopping' — they are
    # the primary structured-price sources. The user can deselect them, but the
    # code must never drop them by accident. See
    # .claude/investigations/beat-this-price.md.
    pattern_engines = narrow_engines(
        ['ddg', 'bing', 'google', 'yahoo',
         'shopping', 'bing_shopping', 'yahoo_shopping', 'ddg_shopping'],
        selected_engines)
    shopping_on = selected_engines is None or 'shopping' in selected_engines

    # Build all search tasks; track which pattern each task belongs to.
    all_tasks: List[Any] = []
    task_pids: List[str] = []   # parallel list: pattern_id per task slot

    if pattern_engines:
        for pid, query in pattern_queries:
            base = ' '.join(filter(None, [query] + char_parts + [price_hint]))
            all_tasks.append(multi_engine_search(
                f"buy {base} supplier wholesale price", max_results=max_results * 2,
                engines=pattern_engines,
                match_pct=30, log_label="beat price",
            ))
            task_pids.append(pid)

    # Supplemental searches on model/category (no pattern attribution).
    supp_start = len(all_tasks)
    if model_number:
        model_engines = narrow_engines(['bing', 'google', 'yahoo'], selected_engines)
        if model_engines:
            all_tasks.append(multi_engine_search(
                f"buy {model_number} {price_hint}".strip(), max_results=max_results * 2,
                engines=model_engines, match_pct=30, log_label="beat price",
            ))
        if shopping_on:
            all_tasks.append(_google_shopping_search(f"buy {model_number}", max_results=max_results))
    if category:
        cat_engines = narrow_engines(['ddg', 'bing', 'google', 'yahoo'], selected_engines)
        if cat_engines:
            all_tasks.append(multi_engine_search(
                f"buy {category} wholesale {price_hint}".strip(), max_results=max_results * 2,
                engines=cat_engines, match_pct=30, log_label="beat price",
            ))

    all_raw, images = await asyncio.gather(
        asyncio.gather(*all_tasks, return_exceptions=True),
        _image_search(f"buy {description}", max_results=max_results),
    )
    img_idx = _img_index(images) if isinstance(images, list) else {}

    # Group task results back by pattern.
    pattern_raw: Dict[str, List] = {pid: [] for pid, _ in pattern_queries}
    for i, raw in enumerate(all_raw[:supp_start]):
        pattern_raw[task_pids[i]].append(raw)
    supp_raw = list(all_raw[supp_start:])

    # Score every result with fuzzy match; dedup by domain keeping best score.
    domain_best: Dict[str, Dict] = {}
    per_pattern_best: Dict[str, int] = {pid: 0 for pid, _ in pattern_queries}

    def _score_and_merge(result: Dict, pid: str) -> None:
        score = fuzzy_score(result.get('title', ''), result.get('description', ''), description)
        result['fuzzy_score'] = score
        result['pattern_id'] = pid
        if score > per_pattern_best.get(pid, 0):
            per_pattern_best[pid] = score
        domain = result['domain']
        if domain not in domain_best or score > domain_best[domain].get('fuzzy_score', 0):
            # When the new winner has no price but the previous entry did, carry the price over.
            existing_price = (domain_best.get(domain) or {}).get('price')
            if existing_price and not result.get('price'):
                result = {**result, 'price': existing_price}
            domain_best[domain] = result
        elif result.get('price') and not domain_best[domain].get('price'):
            # Lower-score result has price; promote price to the winner.
            domain_best[domain] = {**domain_best[domain], 'price': result['price']}

    for pid, raw in pattern_raw.items():
        if not raw or all(isinstance(r, Exception) for r in raw):
            continue
        for result in _aggregate_and_rank(raw, img_idx, max_results * 5):
            _score_and_merge(result, pid)

    if supp_raw and not all(isinstance(r, Exception) for r in supp_raw):
        for result in _aggregate_and_rank(supp_raw, img_idx, max_results * 3):
            _score_and_merge(result, 'supplemental')

    # Sort by fuzzy score descending.  Apply the 30% floor only when enough
    # results clear it; otherwise fall back to the top-N by score so the user
    # always sees something rather than an empty list.
    ranked = sorted(domain_best.values(), key=lambda r: -(r.get('fuzzy_score') or 0))
    above_threshold = [r for r in ranked if (r.get('fuzzy_score') or 0) >= 30]
    pool = above_threshold if len(above_threshold) >= 3 else ranked
    results = await _enrich_prices(pool[:max_results])
    return results, per_pattern_best
