# Session State — 2026-10-29

## Rebrand to domainComp v3 + integrity coverage for ~/dev

- App now brands itself **domainComp v3**: browser title, page header, sidebar (v3.0), FastAPI title/version (3.0.0), startup/shutdown logs, CLI header, `start.sh`/`start.py`/`stop.sh` messages, notification email identity (`[domainComp]` subject, `domainComp` sender). No logic changes; 44 tests pass; verified live at https://localhost:8743.
- `bakerywholesalers.com` scans work again: the block was a Little Snitch deny rule (`iTerm2 via python@3.14 → bakery-wholesalers.myshopify.com:443`, flipped to deny by ls-week-review on 2026-09-28, 5,301 hits). User flipped it back to allow; scan completed: 2,743 products, 17 menus. All three stores now compare green.
- **evw-integrity tier E** (in `/Users/evw/dev/security`): hash-only coverage of `~/dev` code, 15-min sweep (B,C,E) + nightly full (A–E). Hash-only by design — project git repos are the content record. DEV_EXCLUDE_RE skips venvs/builds/caches/backups/DBs/archives. Deployed via `sudo bash evw-integrity-setup.sh` (re-run to pick up E).
- Investigation note: no evidence of unauthorized changes to this repo — git fsck clean, all 300 commits by owner identities, local == origin, no webhooks/unknown collaborators. Kimi session wire logs (security workspace, session_1e159d14, 2026-10-28) fully account for yesterday's work.

# Session State — 2026-10-28

## Store menus, catalog comparison, and individual transfer

- Added **Store Menus & Sync** to the dashboard with live Shopify scans, menu comparison, product comparison, menu coverage/duplicate audits, and per-product field transfer.
- Added persistent snapshots under `data/scan_cache/`; products are matched across stores by Shopify handle.
- Catalog comparison covers scalar product fields, options, variants/prices, images, metafields, and collection membership.
- Menu audits include nested items, direct product links, custom/smart collection representation, missing products, duplicate product links, and unresolved links.
- Transfers require preview + confirmation and operate on one selected product/field set only. Creation is optional, destination variants are preserved, and image deletion requires separate opt-in.
- Shopify compatibility lessons: query active/draft/archived separately (`status=any` returned zero); smart-collection products must be read through GraphQL; bulk metafield reads use `/metafields.json` with `owner_resource=product`.
- Verification: 44 tests pass; full browser workflow passes through menu audit, product comparison, and real transfer preview without writes. Live menu reads succeed on all three stores. Full catalog scans verified on donut-equipment (2,826) and donut-supplies (2,746); bakerywholesalers remained unreachable with `All connection attempts failed` after a retry. Comparison APIs show successful snapshots and mark failed stores unavailable rather than blocking all results.

## Resume tomorrow — 2026-10-29

- Repo/branch: `/Users/evw/dev/domainCompv3`, `search-engine-selection`; GitHub remote is `origin` (`evweath/donut-intel`).
- Local pre-commit backup: `/Users/evw/dev/local-backups/domainCompv3/domainCompv3-20261028-182530.tar.gz` (verified, 2,789 entries, 189,364,489 bytes). Includes source, Git history, DB, logs, and live scan snapshots; credentials, private keys, and regenerable environments are excluded.
- Start with `cd /Users/evw/dev/domainCompv3 && bash start.sh`, then open `https://localhost:8743` → **Store Menus & Sync**. domainSync uses port 8800 if needed.
- Run checks with `.venv/bin/python -m pytest tests -q` and `node --check frontend/js/app.js`; expected baseline is 44 passing tests.
- Retry `bakerywholesalers.com` when its connection is available. Its last error was `All connection attempts failed`; the other two stores have valid snapshots and remain usable. Deselect it for an all-green comparison or retry its scan individually.
- No live product write was performed. Before the first real transfer, review one product and a small field set, verify the preview carefully, and only then approve the write.
- `.claude/settings.local.json` and `logs/server.out` are local-only changes and are intentionally not included in the feature commit. `data/scan_cache/` is ignored by Git but included in the local backup.

# Previous Session State — 2026-06-09T21:30Z

## Accomplished This Session

- **Renamed app to prodComp** — updated all user-facing strings in app.py, start.py, stop.sh, setup_env.py, setup_macos.sh, cli.py, frontend/index.html (title tag + headers)
- **Removed 8 pages** from the app: store-compare, shopify-sync, live-sync, find-customers, source-sync (sync tab), source-products, duplicates, system-of-record
- **Deleted backend modules entirely:** `backend/shopify/` (all 6 files), `backend/dedup/` (4 files), `backend/search/pages/find_customers.py`
- **Cleaned backend/api/routes.py** (~1920 lines removed): removed all routes for deleted pages, imports for deleted models/modules, dead helper functions, scan-cycle routes, shopify-credentials routes, domain-comparison route
- **Cleaned backend/database/models.py:** removed `DuplicateCandidate`, `ShopifyProductMapping`, `ShopifyStoreProductId`, `ShopifySavedWebhook`, `FindCustomerSearch`, `FindCustomerResult` models
- **Cleaned backend/scheduler/scheduler.py:** removed dedup job type
- **Cleaned backend/search/engine.py:** removed find_customers re-exports
- **Cleaned frontend/index.html** (~2185 lines removed): removed all 8 page sections, nav items, cycle-status UI, dedup settings section, "Run Deduplication" quick action, Shopify settings blocks
- **Cleaned frontend/js/app.js** (~1044 lines removed): removed all state vars and methods for deleted pages, cycle management, Shopify webhook management, dedup WS events
- **All 8 tests pass** after all changes
- **Pushed to GitHub** origin/main (commit 70408b6)

## In Progress

- Nothing; session closed cleanly.

## Next Steps

1. Start the server (`bash start.sh`) and verify all 11 remaining pages load correctly in browser
2. Check the dashboard stats grid looks correct (removed "Pending Duplicates" card — was 4-col grid, now 3)
3. If needed, update `grid-cols-2 lg:grid-cols-4` → `grid-cols-3` in dashboard stats section (`frontend/index.html` ~line 158)
4. Check scans page works for individual domain scans

## Key Context

- **Kept pages:** dashboard, products, scans, find-product, beat-price, competitors, pricing, scheduler, reports, export, settings
- **Removed pages:** store-compare, shopify-sync, live-sync, find-customers, sync (source sync), source-products, duplicates, system-of-record
- **App name:** prodComp (was Donut Intel)
- **Same repo:** github.com:evweath/donut-intel.git, branch: main
- **DB file still named:** donut_intel.db (not renamed)
- **Scan cycle concept removed:** `/api/scan/cycle-status` and related routes gone; scans page still works for individual domain scans via `/api/scan/sources`
- **Dashboard grid:** stat cards reduced from 4 to 3 — layout tweak may be needed
- **Auth**: POST `/api/auth/login` `{"username":"admin","password":"changeme"}`
- **Server:** `bash start.sh` / `lsof -ti :8743 | xargs kill -9`
- **Tests:** `.venv/bin/python -m pytest tests/ -v` — 8 pass
