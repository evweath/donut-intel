"""
Backward-compatibility shim for the search layer.

The search code was split into a shared core (plumbing) and per-page modules so
that one page's logic can be changed without touching another's, while the fragile
engine adapters and parsing primitives live in exactly one place.

    backend/search/core/      ← provider adapters + parsing + ranking (one copy)
    backend/search/pages/     ← one module per app page (query + scoring + shaping)

This module re-exports the public surface so existing imports
(`from backend.search.engine import ...`) keep working. New code should import
directly from the core/ or pages/ module it needs. See CLAUDE.md.
"""
# Core — fetch / parse / engine adapters / ranking
from backend.search.core.constants import (  # noqa: F401
    _BING_SKIP_DOMAINS,
    _DDG_SEARCH_LOCK,
    _NOISE_DOMAINS,
    _SEARCH_HEADERS,
    _SITE_SEARCH_PATTERNS,
    _SITE_SKIP_HREFS,
)
from backend.search.core.fetch import _curl_get, _run_sync  # noqa: F401
from backend.search.core.parse import (  # noqa: F401
    _MODEL_RE,
    _PRICE_RE,
    _cite_to_url,
    _domain,
    _extract_model,
    _extract_price,
    _img_index,
    _is_homepage,
)
from backend.search.core.engines import (  # noqa: F401
    _bing_search,
    _bing_shopping_search,
    _duckduckgo_shopping_search,
    _google_search,
    _google_shopping_search,
    _image_search,
    _parse_site_search_results,
    _search_competitor_site,
    _serpapi_shopping_search,
    _text_search,
    _yahoo_search,
    _yahoo_shopping_search,
)
from backend.search.core.rank import (  # noqa: F401
    _aggregate_and_rank,
    _enrich_prices,
    fuzzy_score,
    multi_engine_search,
)

# Pages — one public entry point per app page
from backend.search.pages.beat_price import find_suppliers  # noqa: F401
from backend.search.pages.competitor_site import search_competitor_websites  # noqa: F401
from backend.search.pages.find_product import find_products  # noqa: F401
