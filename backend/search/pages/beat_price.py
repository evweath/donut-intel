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

import re as _re

from backend.search.core.constants import narrow_engines
from backend.search.core.engines import _google_shopping_search, _image_search
from backend.search.core.parse import _img_index, filter_usa_domains


def _price_to_float(val: Any) -> Optional[float]:
    """'$1,029.99' / 1029.99 / None -> float | None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    digits = _re.sub(r'[^\d.]', '', str(val))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def _price_within(price: Any, price_min: Optional[float], price_max: Optional[float]) -> bool:
    """True if the price satisfies the user's limit. With a limit set, an unknown
    price fails (we can't confirm it qualifies). No limit set -> always True."""
    if price_min is None and price_max is None:
        return True
    p = _price_to_float(price)
    if p is None:
        return False
    if price_min is not None and p < price_min:
        return False
    if price_max is not None and p > price_max:
        return False
    return True
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
    exclude_domains: Optional[set] = None,
    exact_query: bool = False,
    min_confidence: Optional[float] = None,
    usa_only: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Find alternate suppliers using pattern-based title queries.

    pattern_queries is an ordered list of (pattern_id, query_text) produced by
    pattern_learner.generate_queries().  Each pattern runs its own concurrent
    search; all results are fuzzy-scored against the original description,
    deduplicated by domain, sorted best-first.

    Returns (successful, potential, per_pattern_best_fuzzy):
      * successful — fuzzy match >= floor AND price within the user's price limit
        (capped at max_results). These are the "successful product matches".
      * potential — fuzzy match >= floor but price OUTSIDE the limit (or unknown):
        the product matches but the price doesn't qualify.
      * per_pattern_best_fuzzy — highest fuzzy score each pattern_id achieved.
    floor = min_confidence if given else 30. With usa_only (default), non-US
    country-TLD domains are dropped before classification.
    """
    char_parts: List[str] = [str(v) for v in (characteristics or {}).values() if v]
    price_hint = f"under ${price_max:.0f}" if price_max else (f"over ${price_min:.0f}" if price_min else '')
    exclude = exclude_domains or set()   # competitors already found (for "continue")

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
         'shopping', 'bing_shopping', 'yahoo_shopping', 'ddg_shopping',
         'costco', 'samsclub', 'ubereats'],
        selected_engines)
    shopping_on = selected_engines is None or 'shopping' in selected_engines

    # Build all search tasks; track which pattern each task belongs to.
    all_tasks: List[Any] = []
    task_pids: List[str] = []   # parallel list: pattern_id per task slot

    if pattern_engines:
        for pid, query in pattern_queries:
            if exact_query:
                # Free-text path: send the user's input verbatim — no wrapper words,
                # no appended characteristics/price text. See routes free-text path.
                search_query = query
            else:
                base = ' '.join(filter(None, [query] + char_parts + [price_hint]))
                search_query = f"buy {base} supplier wholesale price"
            all_tasks.append(multi_engine_search(
                search_query, max_results=max_results * 2,
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
        domain = result['domain']
        if domain in exclude:   # skip competitors already returned by a prior batch
            return
        score = fuzzy_score(result.get('title', ''), result.get('description', ''), description)
        result['fuzzy_score'] = score
        result['pattern_id'] = pid
        if score > per_pattern_best.get(pid, 0):
            per_pattern_best[pid] = score
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
    # A candidate must clear the fuzzy floor to count at all (successful OR
    # potential). Sub-floor results are dropped entirely.
    floor = min_confidence if min_confidence is not None else 30
    ranked = sorted(domain_best.values(), key=lambda r: -(r.get('fuzzy_score') or 0))
    candidates = [r for r in ranked if (r.get('fuzzy_score') or 0) >= floor]

    # "USA websites only" filter (default on) — drop non-US country-TLD domains.
    if usa_only:
        candidates = filter_usa_domains(candidates)

    # Enrich prices so candidates can be split by the price limit. Bound the
    # number of live price fetches for performance.
    candidates = await _enrich_prices(candidates[: max(max_results * 4, 20)])

    # Split into successful (price within limit) vs potential (matches the
    # product but price is outside the limit / unknown).
    successful: List[Dict[str, Any]] = []
    potential: List[Dict[str, Any]] = []
    for r in candidates:
        (successful if _price_within(r.get('price'), price_min, price_max) else potential).append(r)

    return successful[:max_results], potential, per_pattern_best
