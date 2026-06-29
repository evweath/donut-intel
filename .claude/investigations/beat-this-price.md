# Beat This Price — Investigation File

## Architecture

```
POST /api/beat-price
  → routes.py: find_suppliers(description, price_min, price_max, ...)   [search/pages/beat_price.py]
    → core/rank.py: multi_engine_search(query, engines=[...])  ← CRITICAL: must include 'shopping','bing_shopping'
    → beat_price.py: _score_and_merge()  ← preserves price across domain dedup
    → core/rank.py: _aggregate_and_rank()
  → routes.py: returns BeatPriceResult rows (or cached fallback)
Frontend: index.html:2303 renders price column; app.js:2036 colors price diff
```

**NOTE (2026-06-08 refactor):** the search layer was split into `core/` (plumbing)
and `pages/` (per-page logic). `find_suppliers` and `_score_and_merge` now live in
`backend/search/pages/beat_price.py`. `multi_engine_search`/`_aggregate_and_rank`
live in `backend/search/core/rank.py`. `backend/search/engine.py` is now a re-export
shim. The engine-list and price-carry-over logic are unchanged — just relocated.
Tests patch `backend.search.pages.beat_price.multi_engine_search` (patch where used).

## Confirmed Root Causes (do not re-investigate)

### Price null for all results (RESOLVED — 2026-06-05)
- **Root cause:** `find_suppliers` called `multi_engine_search` with only organic engines (`ddg`, `bing`, `google`, `yahoo`). Shopping engines were in a separate `_google_shopping_search` call that returned 0 results.
- **Fix:** Added `shopping`, `bing_shopping` to the `multi_engine_search` call in the pattern loop. Now in `backend/search/pages/beat_price.py` (was `engine.py:1198` pre-refactor).
- **Key insight:** Organic search snippets almost never contain `$XX.XX` price patterns. Shopping engines are the only reliable source. Any future "price null" bug: check the engine list first.

### Price lost during domain dedup (RESOLVED — 2026-06-05)
- **Root cause:** `_score_and_merge` overwrote a lower-fuzzy shopping result (which had a price) with a higher-fuzzy organic result (no price), discarding the price.
- **Fix:** Added price carry-over logic in `_score_and_merge` (now in `backend/search/pages/beat_price.py`, was `engine.py:1241–1247`). If the new winner has no price but the displaced entry did, copy the price. Also promotes price from lower-score result if winner lacks one.

### Price column hidden when null (RESOLVED — 2026-06-05)
- **Root cause:** Frontend template had `x-show="r.price != null"` on outer price div, hiding the entire column slot when price was null.
- **Fix:** Removed the outer `x-show`; price slot always renders — shows `—` for null, actual value otherwise (`index.html:2303`).
- **Lesson:** Never hide the entire UI slot for missing data — it makes null invisible vs. "data shows slot is empty."

### Color logic inverted (RESOLVED — 2026-06-05)
- **Root cause:** Competitor cheaper than us was colored GREEN, competitor more expensive was RED. Inverted.
- **Fix:** Corrected in `index.html:2305`, `index.html:2309`, and `app.js:2036`.
- **Rule:** Competitor cheaper = RED (bad for us). Competitor more expensive = GREEN (we win).

## Known Failure Modes

- **Rate limiting:** Empty results from `find_suppliers` are usually Bing/Google/DDG rate-limiting, not a code bug. Cached fallback added at `routes.py:2925` — loads most recent `BeatPriceResult` rows from DB. Wait ~1 hour for rate limits to clear.
- **Zero shopping results despite correct engine list:** Check if the SerpAPI key in `config/settings.yaml` is valid and has quota.

## Failed Attempts (do not repeat)

| Session | What was tried | Why it failed |
|---|---|---|
| ~5 sessions before 2026-06-05 | Frontend null-check fixes, CSS display tweaks, color class changes | Root cause was upstream — `r.price` was null before reaching the frontend |
| Pre-fix | Checked `_score_and_merge` dedup logic | Dedup was a secondary issue; primary was shopping engines missing entirely |

## Feature Changes

### Verbatim free-text query + min-confidence + sortable results (2026-06-29)
- **Free-text "describe what you need" is now verbatim.** `find_suppliers` gained
  `exact_query: bool`. When True (set only by the free-text route path), the query
  passed to `multi_engine_search` is the user's input as-is — no
  `buy ... supplier wholesale price` wrapper, no appended char/price text. The
  route also stops running `generate_queries` decoration on this path and passes
  `pattern_queries=[("full", description)]`. Product/catalog path is unchanged
  (still wraps). Tests: `test_find_suppliers_exact_query_is_verbatim`,
  `test_find_suppliers_default_query_keeps_wrapper`.
- **Confidence %.** `BeatPriceRequest.min_confidence` (and `find_suppliers`
  `min_confidence`) replace the hardcoded 30 fuzzy floor when provided. UI field in
  the right-column search params. Test: `test_find_suppliers_min_confidence_filters_low_scores`.
- **Results UI** (`index.html` grouped + flat blocks): each line shows the search
  timestamp + params on the left (tagged client-side in `_tagBeatResults`); a
  confidence-% column (`r.fuzzy_score`); "Our Price" column immediately left of the
  vendor price; default sort cheapest-first; clickable sort by vendor/confidence/price
  via the shared `setSort`/`_sortRows`/`sortIcon` helpers (`beatPriceSort` state).
- **Catalog list height** bumped `max-h-72` → `max-h-[36rem]` so its bottom aligns
  with the right column.

### Search-history rework (2026-06-29) — shared with Find-Product page
- **0-result entries hidden:** `beatPriceHistoryVisible()` already filtered these;
  added `findProductHistoryVisible()` and pointed the find-product history template at it.
- **Per-result delete:** new `DELETE /api/search/beat-price/result/{id}` and
  `DELETE /api/search/find-product/result/{id}`. Frontend ✕ button per line →
  `deleteBeatPriceResult` / `deleteFindProductResult` then reload history.
- **Price columns:** history endpoints now return per-result `id`, `our_price`, and
  (beat-price) `fuzzy_score`. UI shows match % | Our $ | Competitor $ right-aligned,
  competitor price far right. `our_price`: beat-price = result.product_id → product
  price; find-product = first selected product's price (null for free-text searches).
- **match % persistence:** added `beat_price_results.fuzzy_score` column (models.py +
  `_MIGRATIONS` in db.py) and persist `r.get("fuzzy_score")` on save. Pre-existing
  beat-price history rows show "—" (no stored score); new searches populate it.
- **+N more is now a button** that toggles `bp/fpHistoryExpanded[search.id]` to show all
  result lines (collapsed = top 3).
- **Sortable:** per-page `bpHistorySort`/`fpHistorySort` state + shared
  `setSort`/`_sortRows`/`sortIcon`.

### History is a flat, globally-sortable table (2026-06-29, revised)
Per user follow-up: the history is NOT grouped/sorted per search entry. Instead
`historyFlatRows(searchesVisible, sortState)` flattens **every** result line across
all non-empty searches (tagging each with its search's `_query` + `_searched_at`),
sorts newest-first, caps at `HISTORY_ROW_LIMIT = 50`, then applies the user's column
sort to those 50. So sorting reorders the whole pool, not within entries. The grouped
per-entry layout and the "+N more" expand were removed (replaced by the 50-row cap +
a "Showing X of Y result lines" note). Columns: Searched (date+query) | Result/Vendor
| Match % | Our $ | Competitor $, all sortable. `our_price` = first selected product's
canonical price (confirmed by user = the product shown first in catalog). Verified via
Playwright: 50-row cap, rows span multiple searches, price-sort ascends globally.

## Open Questions

- Does `_google_shopping_search` ever return results? It's still called for model-number supplemental searches (`engine.py:1209`). Unclear if it works reliably vs. just `multi_engine_search` with shopping engines.
