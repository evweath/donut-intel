"""
Tests for backend/search/engine.py

These tests use mocks so they run without network access.
When a test in this file fails on a bug you're investigating, update
.claude/investigations/<feature>.md with what the test revealed.
"""
import asyncio
import sys
import os
from unittest.mock import AsyncMock, patch, call
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.search.engine import find_suppliers


# ---------------------------------------------------------------------------
# Beat This Price — price field correctness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_suppliers_includes_shopping_engines():
    """
    Regression: find_suppliers must call multi_engine_search with 'shopping'
    and 'bing_shopping' in the engines list. Organic-only engines never return
    structured price data ($XX.XX), so omitting them causes r.price = None for
    every result.

    If this test fails: the engine list at engine.py:1198 has been changed to
    exclude shopping engines. Do NOT fix by adjusting the frontend — fix the
    engine list here.
    """
    captured_engine_calls = []

    async def fake_multi_engine_search(query, max_results=10, engines=None, **kwargs):
        captured_engine_calls.append(engines or [])
        return []

    with patch('backend.search.pages.beat_price.multi_engine_search', side_effect=fake_multi_engine_search), \
         patch('backend.search.pages.beat_price._google_shopping_search', new_callable=AsyncMock, return_value=[]), \
         patch('backend.search.pages.beat_price._image_search', new_callable=AsyncMock, return_value=[]):
        await find_suppliers(description='Acme Widget Model X100', max_results=5)

    pattern_calls = captured_engine_calls  # all calls from the pattern loop
    assert len(pattern_calls) >= 1, 'find_suppliers made no multi_engine_search calls'

    for engines in pattern_calls:
        assert 'shopping' in engines, (
            f'shopping engine missing from call with engines={engines}. '
            'Shopping engines are the only source of structured price data.'
        )
        assert 'bing_shopping' in engines, (
            f'bing_shopping engine missing from call with engines={engines}.'
        )


@pytest.mark.asyncio
async def test_find_suppliers_price_preserved_from_shopping_result():
    """
    Regression: when a shopping result (with price) has a lower fuzzy score than
    an organic result (no price) for the same domain, the price must be carried
    forward to the winning result. Previously _score_and_merge discarded it.

    If this test fails: check _score_and_merge at engine.py:1241 — the price
    carry-over logic has been removed or broken.
    """
    shopping_result = {
        'url': 'https://example.com/widget-x100',
        'domain': 'example.com',
        'title': 'Acme Widget',  # lower fuzzy score — vague title
        'description': 'Widget for sale',
        'price': '$49.99',
        'source': 'shopping',
    }
    organic_result = {
        'url': 'https://example.com/acme-widget-model-x100',
        'domain': 'example.com',
        'title': 'Acme Widget Model X100 — Buy Online',  # higher fuzzy score
        'description': 'Official Acme Widget Model X100 product page',
        'price': None,
        'source': 'google',
    }

    call_count = 0

    async def fake_multi_engine_search(query, max_results=10, engines=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [organic_result, shopping_result]
        return []

    with patch('backend.search.pages.beat_price.multi_engine_search', side_effect=fake_multi_engine_search), \
         patch('backend.search.pages.beat_price._google_shopping_search', new_callable=AsyncMock, return_value=[]), \
         patch('backend.search.pages.beat_price._image_search', new_callable=AsyncMock, return_value=[]):
        results, _potential, _ = await find_suppliers(
            description='Acme Widget Model X100',
            max_results=5,
        )

    example_results = [r for r in results if r.get('domain') == 'example.com']
    assert len(example_results) == 1, 'expected exactly one result for example.com after domain dedup'

    winner = example_results[0]
    assert winner.get('price') is not None, (
        f'Price was lost during domain dedup. Winner: {winner}. '
        'Check _score_and_merge price carry-over logic at engine.py:1241.'
    )
    assert winner['price'] == '$49.99', (
        f'Wrong price on winner: {winner["price"]!r}. Expected $49.99 from shopping result.'
    )


# ---------------------------------------------------------------------------
# Search-engine selection — user-chosen engine narrowing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_suppliers_narrows_to_selected_engines():
    """
    Passing selected_engines must intersect each query's engine list with the
    selection, and must skip the direct Google Shopping call when 'shopping' is
    not selected. Powers the per-page search-engine checkbox UI.
    """
    captured_engine_calls = []

    async def fake_multi_engine_search(query, max_results=10, engines=None, **kwargs):
        captured_engine_calls.append(engines or [])
        return []

    shopping_mock = AsyncMock(return_value=[])
    with patch('backend.search.pages.beat_price.multi_engine_search', side_effect=fake_multi_engine_search), \
         patch('backend.search.pages.beat_price._google_shopping_search', new=shopping_mock), \
         patch('backend.search.pages.beat_price._image_search', new_callable=AsyncMock, return_value=[]):
        await find_suppliers(
            description='Acme Widget Model X100',
            model_number='X100',
            category='widgets',
            selected_engines={'google', 'bing'},
        )

    assert captured_engine_calls, 'no multi_engine_search calls were made'
    for engines in captured_engine_calls:
        # Every call must be a subset of the user's selection — nothing leaks in.
        assert set(engines).issubset({'google', 'bing'}), (
            f'call used un-selected engines: {engines}'
        )
        assert engines, 'narrowed engine list should be non-empty when selection overlaps'
    # 'shopping' was not selected, so the direct Google Shopping pass is skipped.
    shopping_mock.assert_not_called()


@pytest.mark.asyncio
async def test_find_suppliers_default_engines_unchanged():
    """selected_engines=None (the default) must preserve the full engine list."""
    captured = []

    async def fake_multi_engine_search(query, max_results=10, engines=None, **kwargs):
        captured.append(engines or [])
        return []

    with patch('backend.search.pages.beat_price.multi_engine_search', side_effect=fake_multi_engine_search), \
         patch('backend.search.pages.beat_price._google_shopping_search', new_callable=AsyncMock, return_value=[]), \
         patch('backend.search.pages.beat_price._image_search', new_callable=AsyncMock, return_value=[]):
        await find_suppliers(description='Acme Widget Model X100')

    assert captured, 'no multi_engine_search calls were made'
    # The pattern query keeps all six default engines including both shopping ones.
    assert 'shopping' in captured[0] and 'bing_shopping' in captured[0]


@pytest.mark.asyncio
async def test_find_suppliers_returns_results_when_shopping_has_prices():
    """
    Integration-style: given shopping results with prices, find_suppliers must
    return at least one result with a non-null price field.

    This is the end-to-end check — if both unit tests above pass but this one
    fails, the issue is in _aggregate_and_rank or the final ranked list assembly.
    """
    shopping_results = [
        {
            'url': f'https://store{i}.com/widget',
            'domain': f'store{i}.com',
            'title': f'Acme Widget Model X100 — Store {i}',
            'description': 'Buy Acme Widget Model X100 online',
            'price': f'${40 + i}.99',
            'source': 'shopping',
        }
        for i in range(1, 4)
    ]

    async def fake_multi_engine_search(query, max_results=10, engines=None, **kwargs):
        return shopping_results

    with patch('backend.search.pages.beat_price.multi_engine_search', side_effect=fake_multi_engine_search), \
         patch('backend.search.pages.beat_price._google_shopping_search', new_callable=AsyncMock, return_value=[]), \
         patch('backend.search.pages.beat_price._image_search', new_callable=AsyncMock, return_value=[]):
        results, _potential, _ = await find_suppliers(
            description='Acme Widget Model X100',
            max_results=5,
        )

    assert len(results) > 0, 'find_suppliers returned no results despite shopping results being available'
    results_with_price = [r for r in results if r.get('price')]
    assert len(results_with_price) > 0, (
        f'No results have a price field. Results: {results}. '
        'Shopping results with prices should flow through to the final list.'
    )


# ---------------------------------------------------------------------------
# Beat This Price — free-text "describe what you need" query is verbatim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_suppliers_exact_query_is_verbatim():
    """
    The free-text "Or describe what you need" path must search for EXACTLY what
    the user typed — no 'buy ... supplier wholesale price' wrapper, no appended
    characteristics or price text. When exact_query=True the query string passed
    to multi_engine_search must equal the user's input verbatim.
    """
    typed = 'commercial donut fryer natural gas 24-count'
    captured_queries = []

    async def fake_multi_engine_search(query, max_results=10, engines=None, **kwargs):
        captured_queries.append(query)
        return []

    with patch('backend.search.pages.beat_price.multi_engine_search', side_effect=fake_multi_engine_search), \
         patch('backend.search.pages.beat_price._google_shopping_search', new_callable=AsyncMock, return_value=[]), \
         patch('backend.search.pages.beat_price._image_search', new_callable=AsyncMock, return_value=[]):
        await find_suppliers(
            description=typed,
            pattern_queries=[('full', typed)],
            exact_query=True,
            price_max=500,                         # must NOT leak into the query
            characteristics={'color': 'red'},      # must NOT leak into the query
            max_results=5,
        )

    assert captured_queries, 'no multi_engine_search calls made'
    assert all(q == typed for q in captured_queries), (
        f'exact_query path altered the search string: {captured_queries!r}. '
        'It must be the verbatim user input with nothing prepended or appended.'
    )


@pytest.mark.asyncio
async def test_find_suppliers_default_query_keeps_wrapper():
    """The catalog/product path (exact_query=False, default) still wraps the
    query with 'buy ... supplier wholesale price' — verbatim behavior is opt-in."""
    captured_queries = []

    async def fake_multi_engine_search(query, max_results=10, engines=None, **kwargs):
        captured_queries.append(query)
        return []

    with patch('backend.search.pages.beat_price.multi_engine_search', side_effect=fake_multi_engine_search), \
         patch('backend.search.pages.beat_price._google_shopping_search', new_callable=AsyncMock, return_value=[]), \
         patch('backend.search.pages.beat_price._image_search', new_callable=AsyncMock, return_value=[]):
        await find_suppliers(description='Acme Widget', max_results=5)

    assert captured_queries and all(
        q.startswith('buy ') and 'supplier wholesale price' in q for q in captured_queries
    ), f'default path should keep the wrapper, got {captured_queries!r}'


# ---------------------------------------------------------------------------
# Beat This Price — user-set minimum confidence floor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_suppliers_min_confidence_filters_low_scores():
    """
    A user-supplied min_confidence raises the fuzzy-match floor. Results scoring
    below it are dropped (as long as enough results clear the bar that the
    never-empty fallback doesn't kick in).
    """
    # Four exact-title matches (high fuzzy) + one vague title (low fuzzy).
    target = 'Acme Widget Model X100'
    strong = [
        {
            'url': f'https://store{i}.com/w', 'domain': f'store{i}.com',
            'title': target, 'description': target, 'price': f'${40 + i}.00',
            'source': 'shopping',
        } for i in range(1, 5)
    ]
    weak = [{
        'url': 'https://vague.com/w', 'domain': 'vague.com',
        'title': 'random unrelated thing', 'description': 'nothing alike',
        'price': '$9.00', 'source': 'shopping',
    }]

    async def fake_multi_engine_search(query, max_results=10, engines=None, **kwargs):
        return strong + weak

    with patch('backend.search.pages.beat_price.multi_engine_search', side_effect=fake_multi_engine_search), \
         patch('backend.search.pages.beat_price._google_shopping_search', new_callable=AsyncMock, return_value=[]), \
         patch('backend.search.pages.beat_price._image_search', new_callable=AsyncMock, return_value=[]):
        results, _potential, _ = await find_suppliers(
            description=target, max_results=10, min_confidence=80,
        )

    domains = {r['domain'] for r in results}
    assert 'vague.com' not in domains, (
        f'low-confidence result survived min_confidence=80 floor: {domains}'
    )
    assert any(d.startswith('store') for d in domains), 'strong matches were dropped'
