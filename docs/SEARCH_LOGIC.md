# Search Logic — Find Product & Beat This Price

> **What this is:** a plain-language description of how the two searches **currently
> behave**, broken into editable rows. It is documentation, *not* a config file the
> app reads — editing it changes nothing on its own. Mark up any row and hand it back,
> and the "Where in code" column says which file/function implements it so the change
> maps to one place.
>
> Last traced from source: 2026-07-08.

---

## A. FIND PRODUCT
*"Find buyable copies of a specific product on the open web (and, optionally, on your competitors' own sites)."*
Entry point: `POST /api/search/find-product` → `routes.search_find_product`.

### A1. Inputs & defaults

| Setting | Default | What it does | Where in code |
|---|---|---|---|
| `product_ids` | — | Catalog products to search for. Their **search term** (or title) becomes the query. | `routes._find_product_context` |
| `query` | — | Free-text query. Used alone, or appended after product terms. | `routes._find_product_context` |
| `model_number` / `category` | from product | Extra context; used for competitor-site queries and competitor de-duplication. | `routes._find_product_context` |
| `max_results` | **10** | Target number of open-web results. | `FindProductRequest` |
| `min_fuzzy_score` | **0** | Minimum match % — **applies ONLY to competitor-site results**, not open-web results. At the default of 0 it filters nothing. | `FindProductRequest` |
| `search_competitor_sites` | **true** | Also search each known competitor's own website. | `FindProductRequest` |
| `engines` | all | Which search engines/shopping surfaces to use (see §C1). | `FindProductRequest` |
| `usa_only` | **true** | Drop open-web results on foreign country-code domains (see §C5). | `FindProductRequest` |

### A2. Step-by-step logic

| # | Step | Details / rules | Where in code |
|---|---|---|---|
| 1 | Build the query text | Joins each selected product's **curated search term** (falls back to catalog title). **Only the first 2 terms are used** — `' '.join(parts[:2])`; extra products (and a query appended after two terms) are silently dropped. | `routes._find_product_context` |
| 2 | Capture "our price" | The catalog price of the **first** selected product, shown for comparison. | `routes._find_product_context` |
| 3 | Build exclusion sets | (a) your own source-store domains; (b) competitor domains that **already track this exact model number**; (c) on "continue", domains already shown. | `routes._find_product_context`, `find_product._should_exclude` |
| 4 | Open-web search | Sends the query **verbatim** (no "buy" prefix, no model/category variants) to the organic engines + shopping surfaces, plus a dedicated higher-volume Google Shopping pass, plus an image search — all concurrently. | `find_product.find_products` |
| 5 | Rank & dedupe | Results deduplicated by domain; ranked by **cross-engine agreement** (how many engines returned that domain), with shopping results weighted 2× and placed first. **No fuzzy-match filtering happens here.** | `rank._aggregate_and_rank` |
| 6 | Fill in missing prices | For results with no price, fetch the page (6 s timeout) and extract the first `$` price. | `rank._enrich_prices` |
| 7 | Competitor-site search *(if enabled)* | For each active competitor domain, query the site's own search page with **product_name → model_number → category** (in that order), fuzzy-score each hit, drop those below `min_fuzzy_score`, keep top 3 per competitor. 64 concurrent, 10 s cap per site. | `competitor_site.search_competitor_websites` |
| 8 | USA filter | `usa_only` drops foreign-ccTLD **open-web** results. Competitor-site results are **not** filtered (you chose those sites). | `routes`, `parse.filter_usa_domains` |
| 9 | Save & return | Persists the search + every result row (web & competitor). Returns web results, competitor results, and "our price". | `routes.search_find_product` |

### A3. "Continue searching"
`POST /api/search/find-product/continue` re-runs **only the open-web search**, excluding domains already shown, and appends new results to the same saved search. The competitor-site pass does **not** re-run.

---

## B. BEAT THIS PRICE
*"Find alternate suppliers/wholesalers who might beat a price for a product."*
Entry point: `POST /api/search/beat-price` → `routes.search_beat_price` → `routes._run_beat_price_search`.

### B1. Inputs & defaults

| Setting | Default | What it does | Where in code |
|---|---|---|---|
| `description` | — | Free-text search (used verbatim). | `BeatPriceRequest` |
| `product_ids` | — | Catalog products to search for (the "grouped" path). | `BeatPriceRequest` |
| `model_number` / `category` | from product | Drive supplemental searches (see B2 step 3). | `BeatPriceRequest` |
| `price_min` / `price_max` | — | The price window. Decides **successful vs potential** (see B2 step 7). | `BeatPriceRequest` |
| `max_results` | **10** | Target number of "successful" results. | `BeatPriceRequest` |
| `min_confidence` | none → **30** | Minimum fuzzy match %. Results below this are **dropped entirely**. | `BeatPriceRequest` |
| `engines` | all | Which engines/shopping surfaces to use. **Must keep the shopping engines** — they are the only structured-price source. | `BeatPriceRequest` |
| `usa_only` | **true** | Drop foreign-ccTLD results. | `BeatPriceRequest` |
| `characteristics` | — | **Currently ignored** (accepted but unused). | *(vestigial)* |

### B2. Step-by-step logic

| # | Step | Details / rules | Where in code |
|---|---|---|---|
| 1 | Pick a path | **Catalog path** (`product_ids`): one result group per product. **Free-text path** (`description`): a single query run verbatim. | `routes._run_beat_price_search` |
| 2 | Build query variants (catalog path) | From the product title, generate progressively shorter queries: full title → words before " - " → drop one trailing word at a time (down to 2 words). Duplicates collapsed. | `pattern_learner.generate_queries` |
| 3 | Run all searches | Each query variant runs against organic engines **+ all shopping surfaces** concurrently. Plus supplemental searches on `model_number` (Bing/Google/Yahoo + Google Shopping) and `category`. Plus an image search. | `beat_price.find_suppliers` |
| 4 | Score every result | Fuzzy-match each result's **title + snippet** against the original description (0–100, rapidfuzz token-set). | `beat_price.find_suppliers`, `rank.fuzzy_score` |
| 5 | Dedupe by domain | Keep the highest-scoring result per domain. If the winner has no price but a lower-scored hit on the same domain does, **carry the price over**. | `beat_price._score_and_merge` |
| 6 | Apply the confidence floor | `floor = min_confidence or 30`. Keep only results **≥ floor**. **There is no top-N fallback** — if nothing clears the floor, the list is empty. Then apply the USA filter and fetch missing prices. | `beat_price.find_suppliers` |
| 7 | Split successful vs potential | **successful** = clears floor **and** price is within the window → capped at `max_results`. **potential** = clears floor but price is outside the window *or unknown*. ⚠️ **With no price window set, everything (incl. unknown prices) is "successful"; "potential" is only ever populated when a min/max is set.** | `beat_price._price_within` |
| 8 | Cached fallback | If the live search returns nothing (rate-limiting/outage) **and** this isn't a "continue" run, show the most recent cached results for that product from the DB. | `routes._run_beat_price_search` |
| 9 | Learn which variants work | Records each query variant's best fuzzy score. After **1000** product searches, locks to the **top 3** best-performing variants. | `pattern_learner` |
| 10 | Save & return | Persists the search + results. Catalog path returns `groups` (one per product); free-text returns a flat `results` + `potential`. | `routes._run_beat_price_search` |

### B3. "Continue searching"
`POST /api/search/beat-price/continue` re-runs the search excluding domains already shown, and skips the cached-DB fallback (so cached rows are never re-shown as "new").

---

## C. SHARED BUILDING BLOCKS (used by both searches)

### C1. Search engines / shopping surfaces
Registry: `constants.SEARCH_ENGINES`. Every page offers all of them; the user's checkboxes narrow the set.

| Key | Name | Type | Returns prices? |
|---|---|---|---|
| `ddg` | DuckDuckGo | organic | rarely |
| `bing` | Bing | organic | rarely |
| `google` | Google | organic | rarely |
| `yahoo` | Yahoo | organic | rarely |
| `shopping` | Google Shopping | shopping | **yes** |
| `bing_shopping` | Bing Shopping | shopping | **yes** |
| `yahoo_shopping` | Walmart (Yahoo Shopping) | shopping | **yes** |
| `ddg_shopping` | DuckDuckGo Shopping | shopping | **yes** |
| `costco` | Costco | shopping | **yes** |
| `samsclub` | Sam's Club | shopping | **yes** |
| `ubereats` | Uber Eats | shopping | **yes** |

> **Key fact:** organic engines almost never return structured prices. The **shopping** engines are the only reliable `$` source — if they're deselected, most results will show no price.

### C2. How results get ranked (`multi_engine_search` / `_aggregate_and_rank`)
| Rule | Behavior |
|---|---|
| Shopping first | Shopping results are collected first (deduped by URL, so several products from one seller all survive) and keep their embedded prices. |
| Organic fills the rest | Remaining slots filled by organic results, deduped by **domain**, ranked by how many engines returned that domain (agreement); shopping weighted 2×. |
| Noise removed | Homepages and blocklisted domains (Google, Wikipedia, Reddit, social media, your own stores, etc.) are dropped. See `constants._NOISE_DOMAINS`. |

### C3. Fuzzy match score
`rapidfuzz` token-set ratio of `title + description` vs the target string, 0–100. Word order and duplicates don't matter; it's a bag-of-words overlap. `rank.fuzzy_score`.

### C4. Price extraction
| Where | How |
|---|---|
| From shopping engines | Price comes embedded in the result. |
| From a snippet | First `$NN.NN` found in the result text. `parse._extract_price`. |
| From the live page | If still missing, fetch the page (6 s) and take the first `$` price in the first 15 KB. `rank._enrich_prices`. |

### C5. "USA websites only" filter
Drops any result whose domain is a **foreign country-code TLD** (`.ca`, `.co.uk`, `.de`, `.com.au`, `.cn`, …). Generic TLDs (`.com`, `.io`, `.co`, `.ai`, …) are treated as US/allowed. `parse.is_usa_domain`.

---

## D. KNOWN QUIRKS & LIMITATIONS (candidates for change)

| # | Quirk | Impact | Where |
|---|---|---|---|
| 1 | **Only the first 2 product terms** are used for a Find-Product query. | Selecting 3+ products (or adding a query after 2 product terms) silently ignores the rest. | `routes._find_product_context` (`parts[:2]`) |
| 2 | **Open-web results are never fuzzy-filtered** in Find Product. | `min_fuzzy_score` only affects competitor-*site* results; irrelevant matches can appear in open-web results. | `find_product.find_products` |
| 3 | **Beat-Price floor has no fallback.** | If nothing scores ≥ the confidence floor, the result list is empty (the code comment/docstring claiming a "top-N fallback" is **stale/inaccurate**). | `beat_price.find_suppliers` |
| 4 | **`characteristics` and `exact_query` are accepted but unused** in Beat Price. | They look like knobs but do nothing; verbatim querying comes from the query builder, not `exact_query`. | `beat_price.find_suppliers` |
| 5 | **"Potential" only appears with a price limit.** | Without a min/max, unknown-price results are counted as "successful". | `beat_price._price_within` |
