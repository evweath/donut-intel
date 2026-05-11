# Session State — 2026-05-11T14:30:00

## Accomplished This Session

- Fixed competitor deletion bug (missing `db.commit()`, missing `is_active` filter)
- Added checkboxes + Select All + Delete Selected to duplicate review screen
- Added domain filter checkboxes to dedup Run button
- Added "Select All on All Pages" for duplicates and source products
- Added Source Products browser with bulk deactivation
- Ensured all 3 source domains appear consistently on all screens
- Added 4 new features: enhanced dashboard (scan phase + log tail), Find This Product, Beat This Price, Find Me New Customers
- Fixed ddgs package rename (`duckduckgo-search` → `ddgs`), pinned `backend='duckduckgo'` to avoid failing fallback engines
- Suppressed noisy ddgs INFO logs in app.py
- Added "Scan All Competitors" and per-row "Scan" buttons to price comparison matrix
- Fixed log-tail poll timer to stop on 401 (session expiry) instead of flooding
- Tightened monitor filter to only catch `[ERROR]`/`[WARNING]` structured log lines
- Deleted unreachable competitor `actionsales.com` (ID 11)
- Added per-competitor scraping profile with auto-learning:
  - Platform detection (Shopify API vs Playwright)
  - 429/rate-limit tracking (timestamp + count)
  - Failure tracking (consecutive failures + last error message)
  - Success tracking (last success date + best product count)
  - Editable rules: min crawl interval, request delay ms, max pages, scraper method, notes
  - UI panel in competitor detail modal (`frontend/index.html:1980+`)
- Fixed uvicorn binding from `0.0.0.0` to `127.0.0.1` (localhost only)

## In Progress

- Nothing actively in progress

## Next Steps

- Restart service: `nohup uvicorn backend.app:app --host 127.0.0.1 --port 8743 --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem >> logs/uvicorn.log 2>&1 &`
- Restart monitor: `tail -f logs/uvicorn.log | grep --line-buffered -E "\[ERROR\]|\[WARNING\]|\[CRITICAL\]|Traceback|Exception"`
- Consider setting `request_delay_ms` on `restaurantsupply.com` scraping profile (hit 429 at page 36 during this session)
- rfbakery.com and chefstore.com fail on sitemap fetches — investigate or delete if consistently unreachable

## Key Context

- Service: `https://127.0.0.1:8743` (self-signed cert, localhost only)
- Auth: admin / changeme (session-based cookies)
- DB: `data/donut_intel.db` (SQLite WAL mode)
- Source domains: donut-supplies.com, donut-equipment.com, bakerywholesalers.com
- Active competitors: ald.kitchen, bakemark.com, bakesupplyplus.com, chefstore.com, chefstoys.com, ckitchen.com, discountbakeryequip.com, katom.com, restaurantsupply.com, restaurantware.com, rfbakery.com
- ddgs package (not duckduckgo-search) — always pass `backend='duckduckgo'`
- Monitor task ID changes each session — always start a fresh Monitor
- git remote: github.com:evweath/donut-intel.git, branch: main
- All changes committed and pushed at `947cd47`
- Scraping profile model: `backend/database/models.py:CompetitorScrapingProfile`
- Scraping profile API: `GET/PUT /api/competitors/{id}/profile` (`backend/api/routes.py:~765`)
