# Shopify Sync — Investigation File

## Architecture

```
Shopify Sync page
  → Settings: Shopify API credentials UI (store URL, access token)
  → Source CSV export: GET /api/shopify/export-csv (source-store products → CSV)
  → Live Sync pipeline:
    → routes.py: POST /api/shopify/sync
      → shopify/: authenticates with destination store API
      → pushes product updates (title, price, description, images, status)
      → returns sync log per product
  → frontend: index.html Shopify Sync section + Live Sync page
```

## Confirmed Root Causes (do not re-investigate)

### Live Sync page not rendering (RESOLVED — 2026-05-22)
- **Root cause:** Alpine.js component initialization order — `x-data` scope was referencing a method before the component mounted.
- **Fix:** Reordered component initialization in `index.html` Shopify Sync section.

### Destination store selector missing (RESOLVED — 2026-05-22)
- **Root cause:** Sync page hardcoded destination store; no UI to select which Shopify store to push to.
- **Fix:** Added destination store dropdown to Shopify Sync page.

### Source site scan using slow HTML scrape instead of API (RESOLVED — 2026-05-19)
- **Root cause:** Source-site scanner was fetching and parsing HTML pages. Shopify stores expose `/products.json` which returns structured data much faster.
- **Fix:** Added `/products.json` fast path for source-site scans in `competitor/scraper.py`.

## Connection Troubleshooting Panel (2026-06-08)

Settings → **🔌 Shopify Connection Log** shows live output of connection attempts to
source stores (2"-wide box, polls every 3s while Settings is open).

- **Where events are emitted:** `backend/shopify/client.py` records to
  `backend/shopify/connlog.py` (a dedicated 200-line ring buffer, separate from the
  main `log_tail` buffer so connection lines aren't pushed out during scans).
  Instrumented points: `fetch_access_token` (auth), `ShopifyClient.__aenter__`
  (session open), `get_shop` (✓ connected), and `_get` (429 / HTTP errors / network
  errors). All source-store reads go through these, so every attempt is captured.
- **Markers:** `→` attempt, `✓` success, `✗` failure, `…` rate-limit wait. Frontend
  colors lines by marker. **Secrets (tokens, client_secret) are never logged** — only
  host, status, and message.
- **API:** `GET /api/shopify/connection-log?n=150` → `{lines:[...]}`;
  `POST /api/shopify/connection-log/clear`.
- **Buffer is per-process, in-memory** — cleared on server restart. If the panel is
  empty after a restart, that's expected until the next connection attempt.

### Connect failures + per-store auth (DIAGNOSED 2026-06-08)
- **Symptom:** `ConnectError: All connection attempts failed` / `ConnectTimeout` when connecting source stores after a credentials reset.
- **Root cause #1 (network):** This machine is on a VPN/corporate network (`utun0–3`, `10.141.222.x`) with **intermittent/flapping outbound egress**. Live tests to Shopify's IP (`23.227.38.74:443`) alternated CONNECTED / "Network is unreachable" / ConnectTimeout within ~2 min, then went 8/8 stable. DNS is dual-stack. The error is purely TCP-layer (no HTTP response) — credentials are irrelevant to it.
  - **Fix applied:** retry-with-backoff on transient `httpx` connection errors in `client.py` (`_with_connect_retry`, 4 attempts, 0.6→1.2→2.4→4.8s) wrapping `fetch_access_token` + all `ShopifyClient` request methods, plus explicit `connect` timeouts. After this, all three stores reached Shopify with no ConnectError.
- **Root cause #2 (per-store creds):** With the network mitigated, `client_credentials` token exchange results split:
  - `donut-supplies.com` → **works end-to-end** (token + get_shop OK, plan professional). Proves the `client_credentials` algorithm + flow are valid (earlier doubt about it was wrong).
  - `donut-equipment.com` (equipmentplus) and `bakerywholesalers.com` (bakery-wholesalers) → Shopify returns **HTTP 400 "Oauth error invalid_request"** at auth. That's a credential rejection, not a network issue → **the client_id/client_secret for those two stores are wrong / mismatched / not configured for the token exchange.** Re-enter those two stores' API credentials (correct app for that store, no whitespace).
- **Diagnostic value of the panel:** `✗ ... ConnectError` = network/egress; `✗ Auth ... 400` = credentials. The panel distinguishes them directly.

## Known Failure Modes

- **Shopify API rate limits:** Shopify enforces 2 req/s for REST API. Bulk sync can hit this. The sync pipeline should throttle — verify it does before adding more products to sync batch.
- **Access token scope:** Shopify access tokens need `write_products` scope. If sync silently fails, check token scopes in the Shopify Partner dashboard.
- **Credentials storage:** Shopify credentials are stored in `config/settings.yaml` — never commit this file. It's in `.gitignore` as of 2026-05-21.

## Failed Attempts (do not repeat)

| Session | What was tried | Why it failed |
|---|---|---|
| — | — | — |

## Open Questions

- Does the Live Sync pipeline handle partial failures? If 3 of 10 products fail to sync, does it report which ones?
- The CSV export — is it used as input to the Live Sync, or are they independent flows?

## Individual product transfer (2026-10-28)

The replacement transfer flow is deliberately not a whole-store sync. A user selects one product, source/destination stores, and individual fields; the app previews source/destination values and requires explicit confirmation. Execution re-reads the live source product and looks up the live destination by handle across active, draft, and archived statuses.

- Existing destination variants are all included in variant updates so unselected variants cannot be removed. Variants are matched by SKU, then option values.
- Product creation is separately confirmed and always carries required title/handle/option structure.
- Image additions and destructive image replacement are separate choices.
- Metafields are written individually; custom collections are created/reused as needed, while smart collections are reported as rule-based rather than manually assigned.
- Responses report per-operation errors and recommend a destination rescan for derived data.
