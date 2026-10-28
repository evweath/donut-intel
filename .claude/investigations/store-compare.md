# Store Compare — Investigation File

## Architecture

```
Store Compare page
  → routes.py: GET /api/store-compare
    → database: queries products across source sites (DS, BW, DE)
    → computes diffs: price, title, description, images, status per product
  → frontend: index.html store-compare section
    → filter panel (attribute checkboxes, diffs-only toggle)
    → per-product attribute status display
```

## Confirmed Root Causes (do not re-investigate)

### Diffs Only filter returning empty results (RESOLVED — 2026-05-21)
- **Root cause:** Diff detection logic was comparing stringified field values without normalization — trailing spaces, case differences, and float formatting caused false "same" comparisons, making Diffs Only filter return nothing.
- **Fix:** Normalized field values before comparison in `routes.py` store-compare diff detection.

### DS/BW products not appearing in DE catalog view (RESOLVED — 2026-05-27)
- **Root cause:** Source-site products (DS = source A, BW = source B) were not being force-merged into the DE catalog view when no exact match existed.
- **Fix:** Added force-merge logic: if a DS/BW product has no DE counterpart, include it as a catalog entry with source=DS/BW.

### Product status not tracked per source site (RESOLVED — 2026-05-21)
- **Root cause:** Status (active/draft/archived) was stored at product level, not per source site. A product archived on BW but active on DE appeared as archived everywhere.
- **Fix:** Added per-source status tracking; status is now stored and compared per site.

## Known Failure Modes

- **Stale scrape data:** Store Compare reflects whatever was last scraped. If a source site hasn't been scraped recently, diffs will be stale. Check scrape timestamps before investigating "wrong" diffs.
- **Fuzzy match misses:** The force-merge logic relies on fuzzy title matching to link DS/BW products to DE products. Very different titles (same product, different naming convention) will appear as separate rows instead of being linked.

## Failed Attempts (do not repeat)

| Session | What was tried | Why it failed |
|---|---|---|
| Pre-2026-05-21 | Filtering by `product.status` field | Status was a single field, not per-source — always matched DE's status |

## Open Questions

- The comprehensive filter panel added 2026-05-27 — does it correctly handle products that exist on only one source? (e.g., DS-only product with no DE counterpart)
- Image diff detection: are we comparing image URLs or actual image content? URL changes on re-upload would trigger false diffs.

## Live snapshot comparison (2026-10-28)

The new Store Menus & Sync page compares live Shopify snapshots keyed by handle rather than the scraped DB projection. It compares title, HTML description, vendor, type, handle, status, tags, template/scope, options, variants (including prices and inventory), images, metafields, and collection membership. Store-specific IDs and timestamps are removed before comparison.

- Read products separately with `status=active`, `draft`, and `archived`: on 2026-10-28 `status=any` returned zero products on the live stores despite each individual status returning results.
- Smart-collection membership uses GraphQL `collection(id:) { products(...) }`. The REST `/smart_collections/{id}/products.json` path returned 404, and `/products.json?collection_id=...` incorrectly returned empty for a collection that GraphQL showed had 59 products.
- Use bulk `/metafields.json?metafield[owner_resource]=product` rather than one request per product, with per-product fallback on failure.
