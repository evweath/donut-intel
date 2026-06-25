"""
Shared constants for the search core: HTTP headers, domain blocklists, and the
URL patterns used when searching a competitor's own site.

These are page-agnostic plumbing — one copy, imported by the engine adapters and
the ranking layer. Do not duplicate these into per-page modules.
"""
import asyncio

_SEARCH_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15'
    ),
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-US,en;q=0.9',
}

_DDG_SEARCH_LOCK = asyncio.Lock()  # serialize DDG calls to avoid rate-limit bans

_BING_SKIP_DOMAINS = frozenset({'bing.com', 'r.bing.com', 'go.microsoft.com', 'microsoft.com',
                                  'facebook.com', 'youtube.com'})

# Domains that should never appear as product results regardless of search engine
_NOISE_DOMAINS = frozenset({
    'google.com', 'shopping.google.com',
    'merriam-webster.com', 'dictionary.com', 'dictionary.cambridge.org',
    'wikipedia.org', 'wikimedia.org',
    'reddit.com', 'quora.com',
    'twitter.com', 'x.com', 'instagram.com', 'pinterest.com', 'tiktok.com',
    'youtube.com', 'facebook.com',
    'yelp.com',
    'offerup.com', 'letgo.com', 'craigslist.org',
    # Own/source stores — should never appear as competitor or supplier results
    'bakerywholesalers.com', 'donut-supplies.com', 'donut-equipment.com',
    # Unrelated sites that pollute results
    'zillow.com',
})

# URL patterns to try when searching a competitor's own site, ordered by likelihood.
_SITE_SEARCH_PATTERNS = [
    '/search?q={q}',
    '/search/?q={q}',
    '/search?query={q}',
    '/search.php?search_query={q}',     # BigCommerce
    '/catalogsearch/result/?q={q}',     # Magento
    '/?s={q}',                          # WordPress / WooCommerce
    '/?search={q}',
    '/search/{q}',                      # Shopify path-style
    '/search?keywords={q}',
    '/search?term={q}',
]

_SITE_SKIP_HREFS = frozenset([
    '/cart', '/login', '/account', '/blog', '/category', '/categories',
    '/collections', '/tag/', '/page/', '/checkout', 'javascript:', 'mailto:',
])

# ---------------------------------------------------------------------------
# Search-engine registry — the single source of truth for every search engine
# and shopping surface the algorithm can query. Order = display order.
#
# `key`   matches the strings multi_engine_search dispatches on (see core/rank).
# `label` is the human name shown in the UI checkboxes.
# `group` buckets engines into 'engine' (organic web search) vs 'shopping'.
#
# Exposed to the frontend via GET /api/search/engines so the checkbox UI can
# never drift from what the backend actually queries. Add a new engine here once
# and wire its key into multi_engine_search; the UI picks it up automatically.
# ---------------------------------------------------------------------------
SEARCH_ENGINES = (
    {'key': 'ddg',            'label': 'DuckDuckGo',           'group': 'engine'},
    {'key': 'bing',           'label': 'Bing',                 'group': 'engine'},
    {'key': 'google',         'label': 'Google',               'group': 'engine'},
    {'key': 'yahoo',          'label': 'Yahoo',                'group': 'engine'},
    {'key': 'shopping',       'label': 'Google Shopping',      'group': 'shopping'},
    {'key': 'bing_shopping',  'label': 'Bing Shopping',        'group': 'shopping'},
    # One engine, two names: scrapes Walmart (it replaced the old JS-only Yahoo
    # Shopping surface). Labelled with both so neither name looks "missing".
    {'key': 'yahoo_shopping', 'label': 'Walmart (Yahoo Shopping)', 'group': 'shopping'},
    {'key': 'ddg_shopping',   'label': 'DuckDuckGo Shopping',  'group': 'shopping'},
)
ALL_ENGINE_KEYS = tuple(e['key'] for e in SEARCH_ENGINES)

# Every page offers every engine/shopping surface; the page modules route the
# selected engines through multi_engine_search so each checkbox is functional.
PAGE_ENGINES = {
    'find_product': ALL_ENGINE_KEYS,
    'beat_price':   ALL_ENGINE_KEYS,
    'competitors':  ALL_ENGINE_KEYS,
    'products':     ALL_ENGINE_KEYS,
}

# Shopping surfaces other than Google Shopping. find_product/beat_price fetch
# Google Shopping through a dedicated higher-volume call (_google_shopping_search)
# and route these remaining shopping engines through multi_engine_search so they
# run only when selected.
NON_GOOGLE_SHOPPING = ('bing_shopping', 'yahoo_shopping', 'ddg_shopping')


def narrow_engines(engine_list, selected):
    """Intersect a query's hardcoded engine list with the user's selection.

    `selected` is None  -> no narrowing; return `engine_list` unchanged so each
                           query keeps its per-variant engine specialization.
    `engine_list` None  -> means "all engines"; expands to ALL_ENGINE_KEYS first.

    Returns a list that may be empty when the user deselected every engine this
    particular query would have used — callers should skip the query in that case.
    """
    if selected is None:
        return engine_list
    base = engine_list if engine_list is not None else list(ALL_ENGINE_KEYS)
    return [e for e in base if e in selected]


def coerce_selected_engines(value):
    """Normalize a request's `engines` field into a set of valid keys, or None.

    Falsy/empty input, or anything containing no recognized key, -> None, which
    every page treats as "search all engines" (the default, backward-compatible
    behavior). Unknown keys are dropped silently.
    """
    if not value:
        return None
    valid = {e for e in value if e in ALL_ENGINE_KEYS}
    return valid or None
