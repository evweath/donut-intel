# Find This Product — investigation notes

## 2026-06-26 — Live log appears empty + searching window/catalog UX

**Reported:** Searching "Fine Granulated Pure Cane Sugar" @ 50% showed nothing in the
Live Search Log; the "Searching…" window didn't show search params; the catalog
picker didn't fill its allocated space.

**Trace:**
`POST /api/search/find-product` (routes.py) → `find_products()` (search/pages/find_product.py)
→ `multi_engine_search()` (search/core/rank.py:176) → `searchlog.record_search()`.

**Root cause(s):**
- The log pipeline works (verified — entry IS recorded), but `record_search` only fires
  *after* all engine fetches complete (30–60s), and the full request runs >180s when
  competitor-site search + price enrichment are on. So the log is blank for the opening
  stretch → perceived as "nothing happening."
- `find_products` never passed `match_pct`, so the log line never showed the confidence %.
- `_curl_get` runs in an executor (fetch.py:16), so it does NOT block the log-poll
  endpoint — ruling out event-loop starvation.

**Fix:**
- routes.py `search_find_product`: emit an immediate `searchlog.record_note('▶ find product: …')`
  with term + min-match % + engine names before the awaits; pass `match_pct=req.min_fuzzy_score`
  into `find_products`.
- find_product.py: added `match_pct` param, forwarded to `multi_engine_search`.
- index.html: added an "active search parameters" block in the results panel's loading
  state (term / engines / confidence); made the catalog card `flex flex-col` with the list
  `flex-1 … style="min-height:13rem"` so it fills the stretched card height.
- app.js: `selectedEngineLabels(page)` helper + `findProductActiveParams` snapshot set in
  `runFindProduct()`.

**Verified:** log shows the start entry ~2s in; completion entry now reads
`🔎 50% match · find product`.

**Lessons:**
- The vendored `frontend/vendor/tailwind.min.css` is **precompiled/purged** — arbitrary
  classes like `min-h-[13rem]` and even `break-words` are NOT in the bundle. Use an inline
  `style="…"` (as the log window does) or a class already present elsewhere in index.html.

## 2026-06-26 — Speed up the search + live per-step progress

**Bottleneck:** `search_competitor_websites` scans ALL active competitor domains
(~271) — for each it tries up to 10 URL `_SITE_SEARCH_PATTERNS`, and `_curl_get`
**retries 3× on timeout**, with NO per-domain cap. A few unresponsive domains
(10 patterns × 3 retries × ~12s) dominated wall-clock → ~198s. `_curl_get` is
genuinely async (primp AsyncClient), NOT thread-pool bound, so concurrency was
artificially low at 5.

**Fixes (all in backend/search):**
- `core/fetch.py`: `_curl_get` gained a `retries` param (default 3, unchanged for
  existing callers).
- `core/engines.py` `_search_competitor_site`: probe each pattern once
  (`retries=1`) with a tight `timeout=5` — fail fast, let the next pattern try.
- `pages/competitor_site.py`: `CONCURRENCY=64`, `PER_DOMAIN_TIMEOUT=10s` hard cap
  via `asyncio.wait_for` per domain. **Result: 198s → ~65s (3×).** The per-domain
  cap is the real bound; concurrency is the safe lever (pure async I/O).

**Live progress logging (separate user request):**
- `core/rank.py` `multi_engine_search`: `_logged()` wrapper emits
  `searching <Engine> for "<term>" (<pct>% match)` as each engine starts and
  `<Engine>: N found` as it finishes.
- `pages/find_product.py`: same for the standalone Google Shopping pass, plus
  `found N web products — fetching prices…`.
- `pages/competitor_site.py`: `record_match()` per competitor hit (with confidence)
  and a `scanned X/Y competitor sites — Z matches so far` heartbeat every 25 sites.

**Note:** repeated test searches trip Bing/Google/DDG rate-limiting (per CLAUDE.md) —
`results: none` after hammering is expected, not a regression.
