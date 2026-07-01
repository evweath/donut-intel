"""
Search-engine adapters — one function per provider/surface.

Text: DuckDuckGo, Bing, Google, Yahoo.
Shopping: Google Shopping (SerpAPI + HTML fallback), Bing Shopping, DuckDuckGo
Shopping, Walmart (formerly Yahoo Shopping).
Plus per-competitor site search and DDG image search.

These are the fragile parts of the system — when a provider changes its HTML,
the fix belongs here, once. Page modules never re-implement an engine; they
select engines via multi_engine_search (core/rank.py).
"""
import asyncio
import base64
import json
import logging
import re
from typing import Any, Dict, List
from urllib.parse import unquote, quote_plus

from backend.search.core.constants import (
    _BING_SKIP_DOMAINS,
    _NOISE_DOMAINS,
    _SITE_SEARCH_PATTERNS,
    _SITE_SKIP_HREFS,
)
from backend.search.core.fetch import _curl_get, _curl_post, _run_sync
from backend.search.core.parse import (
    _PRICE_RE,
    _cite_to_url,
    _domain,
    _extract_model,
    _is_homepage,
)

logger = logging.getLogger(__name__)

# --- Shopping "more results" expansion -------------------------------------
# Shopping surfaces hide several dozen extra products behind a "more"/"see more"
# control. Browser-driven engines (Bing, DuckDuckGo) click it; API/HTML engines
# (Google via SerpAPI, Walmart) page the request instead — same effect, no button.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MORE_BUTTON_MAX_CLICKS = 8        # how many times to click "more"/"see more"
_MORE_BUTTON_SETTLE_MS = 1500      # let newly-loaded products settle after each click
_SHOPPING_SERP_PAGES = 3           # Google Shopping (SerpAPI) result pages to pull
_SHOPPING_IMMERSIVE_CAP = 60       # max products to resolve to direct store URLs (1 SerpAPI credit each);
                                   # sized to cover a whole shopping query (~48) so match-% does the paring

_SHOPPING_WALMART_PAGES = 3        # Walmart search pages to pull


async def _expand_with_more_button(page, label_texts,
                                   max_clicks: int = _MORE_BUTTON_MAX_CLICKS,
                                   settle_ms: int = _MORE_BUTTON_SETTLE_MS) -> int:
    """Repeatedly click a shopping page's "more"/"see more" results button so it
    loads the additional (often several dozen) products it hides behind it.

    Tries each string in ``label_texts`` in order (case-insensitive substring match
    against clickable elements). Best-effort: stops as soon as no matching button is
    found, a click fails, or ``max_clicks`` is reached. Returns the click count.
    """
    clicks = 0
    for _ in range(max_clicks):
        clicked = False
        for text in label_texts:
            try:
                locator = page.locator(
                    f'button:has-text("{text}"), a:has-text("{text}"), '
                    f'[role=button]:has-text("{text}")'
                ).first
                if await locator.count() == 0:
                    continue
                await locator.scroll_into_view_if_needed(timeout=3000)
                await locator.click(timeout=3000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            break
        clicks += 1
        await page.wait_for_timeout(settle_ms)
    return clicks


async def _text_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Search DuckDuckGo HTML endpoint via curl (avoids httpx socket issues)."""
    try:
        q = quote_plus(query)
        # Use the HTML endpoint — no JS required, returns structured result anchors
        html = await _curl_get(
            f'https://html.duckduckgo.com/html/?q={q}&kl=us-en',
            extra_headers=['Referer: https://duckduckgo.com/'],
        )
        if not html:
            return []
        results = []
        seen: set = set()
        # DDG HTML: result links are in <a class="result__a" href="...">
        for m in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        ):
            href = m.group(1).replace('&amp;', '&')
            href = unquote(href)
            # DDG wraps some links in its redirect: //duckduckgo.com/l/?uddg=...
            redir = re.search(r'uddg=([^&"]+)', href)
            if redir:
                href = unquote(redir.group(1))
            # Skip any remaining duckduckgo.com URLs (ads, trackers)
            if 'duckduckgo.com' in href:
                continue
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            d = _domain(href)
            if not d or d in seen:
                continue
            seen.add(d)
            results.append({'href': href, 'title': title, 'body': ''})
            if len(results) >= max_results:
                break
        logger.debug("DDG returned %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("DDG text search failed: %s", exc)
        return []


async def _image_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    def _search():
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.images(query, max_results=max_results, backend='duckduckgo'))
    try:
        return await _run_sync(_search)
    except Exception as exc:
        logger.warning(f"DDG image search failed (images will be missing): {exc}")
        return []


async def _bing_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Bing SERP via curl — reconstructs URLs from cite display tags."""
    try:
        q = quote_plus(query)
        url = f"https://www.bing.com/search?q={q}&count={min(max_results * 2, 50)}&mkt=en-US&setlang=en-US&cc=US"
        html = await _curl_get(url)
        if not html:
            return []
        results = []
        seen: set = set()

        for block in re.finditer(r'class="b_algo[^"]*"(.*?)</li>', html, re.DOTALL):
            b = block.group(1)
            cite_m = re.search(r'<cite[^>]*>(.*?)</cite>', b, re.DOTALL)
            h2_m = re.search(r'<h2[^>]*>(.*?)</h2>', b, re.DOTALL)
            if not cite_m:
                continue
            href = _cite_to_url(cite_m.group(1))
            if _is_homepage(href):
                continue
            title = re.sub(r'<[^>]+>', '', h2_m.group(1)).strip() if h2_m else ''
            d = _domain(href)
            if not d or any(skip in d for skip in _BING_SKIP_DOMAINS) or d in _NOISE_DOMAINS:
                continue
            if d in seen:
                continue
            seen.add(d)
            # Extract snippet from first paragraph in the result block
            snip_m = re.search(r'<p[^>]*>(.*?)</p>', b, re.DOTALL)
            body = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip() if snip_m else ''
            results.append({'href': href, 'title': title, 'body': body})
            if len(results) >= max_results:
                break

        logger.debug("Bing returned %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("Bing search failed: %s", exc)
        return []


async def _google_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Google SERP via curl (best-effort — may be blocked)."""
    try:
        q = quote_plus(query)
        url = f"https://www.google.com/search?q={q}&num={min(max_results * 2, 50)}&hl=en&gl=us"
        html = await _curl_get(url)
        if not html:
            return []
        results = []
        seen: set = set()
        for m in re.finditer(r'href="/url\?q=(https?://(?!www\.google\.com)[^&"]+)&', html):
            href = unquote(m.group(1))
            d = _domain(href)
            if d and d not in seen:
                seen.add(d)
                results.append({'href': href, 'title': '', 'body': ''})
            if len(results) >= max_results:
                break
        logger.debug("Google returned %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("Google search failed: %s", exc)
        return []


async def _yahoo_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Yahoo SERP via curl."""
    try:
        q = quote_plus(query)
        url = f"https://search.yahoo.com/search?p={q}&n={min(max_results * 2, 50)}"
        html = await _curl_get(url)
        if not html:
            return []
        results = []
        seen: set = set()
        # Yahoo encodes real URLs in RU=... query param; strip tracking suffixes
        for m in re.finditer(r'RU=(https?%3[Aa]%2[Ff]%2[Ff][^&"]+)', html):
            href = unquote(m.group(1))
            href = re.sub(r'/RK=\d+/RS=[^/\s"]+', '', href)  # remove Yahoo tracking
            d = _domain(href)
            if d and 'yahoo.com' not in d and d not in seen:
                seen.add(d)
                results.append({'href': href, 'title': '', 'body': ''})
            if len(results) >= max_results:
                break
        return results
    except Exception as exc:
        logger.debug("Yahoo search failed: %s", exc)
        return []


async def _serpapi_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Fetch Google Shopping via SerpAPI.

    Stage 1: organic engine — inline_shopping_results have direct merchant link fields (query-dependent).
    Stage 2: google_shopping engine + immersive product API — fetches direct store URLs and prices
             for the top N results (costs one extra SerpAPI credit per item).
    """
    from backend.config import Config
    api_key = (Config().get('serpapi', 'api_key') or '').strip()
    if not api_key:
        return []
    try:
        import json as _json
        q = quote_plus(query)
        results: List[Dict[str, Any]] = []
        seen: set = set()

        # Stage 1: organic engine (1 credit) — works when Google shows inline shopping results
        organic_url = (
            f"https://serpapi.com/search.json"
            f"?engine=google&q={q}&api_key={api_key}&num=10&gl=us&hl=en"
        )
        html = await _curl_get(organic_url, timeout=20)
        if html:
            data = _json.loads(html)
            for item in data.get('inline_shopping_results', []):
                href = item.get('link', '')
                if not href or 'google.com' in href or href in seen:
                    continue
                domain = _domain(href)
                if not domain:
                    continue
                seen.add(href)
                price_raw = str(item.get('price', '') or '')
                results.append({
                    'href': href, 'url': href, 'domain': domain,
                    'title': item.get('title', '')[:200],
                    'body': f"{item.get('source', domain)} — {price_raw}".strip(' —'),
                    'price': price_raw,
                    'source': 'shopping',
                })
                if len(results) >= max_results:
                    break

        if len(results) >= max_results:
            logger.info("SerpAPI inline shopping: %d results for %r", len(results), query[:60])
            return results
        # Otherwise keep the inline hits and let Stage 2 add the rest — a single
        # shopping query usually has dozens of similar products, and we want them all.

        # Stage 2: google_shopping engine + immersive API for direct store links.
        # Page through several result pages (the API equivalent of clicking the
        # Shopping "more" button) and collect the top products from all of them.
        shopping_rows: List[Dict[str, Any]] = []
        for start in range(0, _SHOPPING_SERP_PAGES * 60, 60):
            shop_url = (
                f"https://serpapi.com/search.json"
                f"?engine=google_shopping&q={q}&api_key={api_key}"
                f"&num=60&start={start}&gl=us&hl=en"
            )
            html2 = await _curl_get(shop_url, timeout=20)
            if not html2:
                break
            try:
                page_rows = _json.loads(html2).get('shopping_results', []) or []
            except Exception:
                break
            if not page_rows:
                break
            shopping_rows.extend(page_rows)
            if len(shopping_rows) >= max_results:
                break
        if not shopping_rows:
            return results  # nothing more to add — return any Stage 1 inline hits

        # Resolve direct store URLs for as many products as the caller asked for
        # (one SerpAPI credit each). The cap is sized to cover a full shopping
        # query (~48 products), so match-% scoring — not credits — does the paring.
        imm_items = [
            item for item in shopping_rows[:min(max_results, _SHOPPING_IMMERSIVE_CAP)]
            if item.get('serpapi_immersive_product_api')
        ]
        if not imm_items:
            return results  # no immersive endpoints — return Stage 1 inline hits
        imm_resps = await asyncio.gather(
            *[_curl_get(f"{item['serpapi_immersive_product_api']}&api_key={api_key}", timeout=15)
              for item in imm_items],
            return_exceptions=True,
        )
        for resp in imm_resps:
            if isinstance(resp, Exception) or not resp:
                continue
            try:
                imm_data = _json.loads(resp)
                for store in imm_data.get('product_results', {}).get('stores', []):
                    href = store.get('link', '')
                    if not href or href in seen:
                        continue
                    domain = _domain(href)
                    if not domain or 'google.com' in domain:
                        continue
                    seen.add(href)
                    price_raw = str(store.get('price', '') or '')
                    results.append({
                        'href': href, 'url': href, 'domain': domain,
                        'title': store.get('title', store.get('name', domain))[:200],
                        'body': f"{store.get('name', domain)} — {price_raw}".strip(' —'),
                        'price': price_raw,
                        'source': 'shopping',
                    })
                    if len(results) >= max_results:
                        break
            except Exception:
                pass
            if len(results) >= max_results:
                break

        logger.info("SerpAPI Shopping (immersive): %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("SerpAPI Shopping failed: %s", exc)
        return []


async def _google_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Google Shopping: try SerpAPI first, fall back to HTML scraping."""
    results = await _serpapi_shopping_search(query, max_results)
    if results:
        return results
    # Fallback: HTML scraping (works only when Google doesn't serve a JS-gate page)
    try:
        q = quote_plus(query)
        url = f"https://www.google.com/search?q={q}&tbm=shop&num=40&hl=en&gl=us"
        html = await _curl_get(url)
        if not html:
            return []
        results: List[Dict[str, Any]] = []
        seen: set = set()

        # Shopping results embed structured blocks. Parse with multiple strategies.
        # Strategy 1: blocks identified by Google Shopping CSS classes / data attributes
        for block_m in re.finditer(
            r'<(?:div|li)[^>]*(?:class="[^"]*(?:sh-dgr|sh-dlr|sh-pr|KZmu8e|i0X6df)[^"]*"|'
            r'data-docid="[^"]+")[^>]*>(.*?)</(?:div|li)>',
            html, re.DOTALL | re.I,
        ):
            block = block_m.group(1)
            price_m = _PRICE_RE.search(block)
            if not price_m:
                continue
            price = price_m.group(0).strip()

            title = ''
            t_m = re.search(r'<h[2-4][^>]*>(.*?)</h[2-4]>', block, re.DOTALL | re.I)
            if t_m:
                title = re.sub(r'<[^>]+>', '', t_m.group(1)).strip()
            if not title:
                al_m = re.search(r'aria-label="([^"]{5,})"', block)
                if al_m:
                    title = al_m.group(1)

            href = ''
            href_m = re.search(r'href="/url\?q=(https?://(?!www\.google\.com)[^&"]+)&', block)
            if href_m:
                href = unquote(href_m.group(1))
            if not href:
                href_m2 = re.search(r'href="(https?://(?!(?:www\.)?google\.com)[^"]+)"', block)
                if href_m2:
                    href = href_m2.group(1)
            if not href:
                continue

            domain = _domain(href)
            if not domain or href in seen:
                continue
            seen.add(href)

            merch_m = re.search(
                r'class="[^"]*(?:aULzUe|NbK1N|merchant|seller)[^"]*"[^>]*>(.*?)</(?:span|div)>',
                block, re.DOTALL | re.I,
            )
            merchant = re.sub(r'<[^>]+>', '', merch_m.group(1)).strip() if merch_m else ''

            results.append({
                'href': href, 'url': href, 'domain': domain,
                'title': title or merchant or domain,
                'body': f"{merchant} — {price}" if merchant else price,
                'price': price, 'source': 'shopping',
            })
            if len(results) >= max_results:
                break

        # Strategy 2: fallback — any non-Google link near a price in the page
        if not results:
            stripped = re.sub(r'<(?:script|style)[^>]*>.*?</(?:script|style)>', ' ', html,
                              flags=re.DOTALL | re.I)
            for m in re.finditer(r'href="(https?://(?!(?:www\.)?google\.com)[^"]+)"', stripped):
                href = m.group(1)
                domain = _domain(href)
                if not domain or href in seen:
                    continue
                ctx = stripped[max(0, m.start() - 100): m.end() + 300]
                price_m = _PRICE_RE.search(ctx)
                if not price_m:
                    continue
                seen.add(href)
                results.append({
                    'href': href, 'url': href, 'domain': domain,
                    'title': domain, 'body': price_m.group(0),
                    'price': price_m.group(0).strip(), 'source': 'shopping',
                })
                if len(results) >= max_results:
                    break

        logger.debug("Google Shopping returned %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("Google Shopping search failed: %s", exc)
        return []


def _parse_bing_shopping_html(html: str, max_results: int) -> List[Dict[str, Any]]:
    """Parse Bing Shopping product cards out of (possibly "see more"-expanded) HTML.

    Merchant URLs are URL-safe-base64-encoded in the u= param of aclick redirects.
    Deduped by merchant URL (not domain) so multiple products from the same store
    are all kept — the whole point of expanding the results.
    """
    results: List[Dict[str, Any]] = []
    seen: set = set()

    # Bing Shopping product cards use anchors with class="br-offLink" that href to
    # https://www.bing.com/aclick?...&u=<URL-safe-base64-encoded-merchant-URL>&...
    for m in re.finditer(r'br-offLink[^>]+href="([^"]+)"', html):
        aclick_url = m.group(1).replace('&amp;', '&')
        u_m = re.search(r'[?&]u=([A-Za-z0-9+/\-_]+=*)', aclick_url)
        if not u_m:
            continue
        b64 = u_m.group(1).replace('-', '+').replace('_', '/')
        b64 += '=' * (-len(b64) % 4)
        try:
            merchant_url = unquote(base64.b64decode(b64).decode('utf-8', errors='replace'))
        except Exception:
            continue
        if not merchant_url.startswith('http'):
            continue
        domain = _domain(merchant_url)
        if not domain or domain in _NOISE_DOMAINS or merchant_url in seen:
            continue

        # Look in a 2000-char window around the anchor for title and price
        card = html[max(0, m.start() - 2000): min(len(html), m.end() + 2000)]

        title = ''
        title_m = re.search(r'<span[^>]+title="([^"]{5,200})"', card)
        if title_m:
            title = title_m.group(1)
        if not title:
            h_m = re.search(r'<h[2-4][^>]*>(.*?)</h[2-4]>', card, re.DOTALL)
            if h_m:
                title = re.sub(r'<[^>]+>', '', h_m.group(1)).strip()

        price = ''
        br_price_m = re.search(r'class="br-price"[^>]*>(.*?)</', card, re.DOTALL)
        if br_price_m:
            price = re.sub(r'<[^>]+>', '', br_price_m.group(1)).strip()
        if not price:
            price_re_m = _PRICE_RE.search(card)
            if price_re_m:
                price = price_re_m.group(0).strip()

        seen.add(merchant_url)
        results.append({
            'href': merchant_url, 'url': merchant_url, 'domain': domain,
            'title': title or domain,
            'body': price,
            'price': price or None,
            'source': 'bing_shopping',
        })
        if len(results) >= max_results:
            break

    return results


async def _bing_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Bing Shopping. Drives a headless browser so we can click the
    "See more" link — which loads several dozen additional products — then parse
    the expanded HTML. Falls back to a static curl fetch if the browser path is
    unavailable (e.g. Playwright not installed)."""
    q = quote_plus(query)
    url = f"https://www.bing.com/shop?q={q}&count={min(max_results * 2, 40)}&cc=US&setlang=en-US"

    html = ''
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=_BROWSER_UA)
            page = await ctx.new_page()
            try:
                await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector('.br-offLink, a[href*="aclick"]', timeout=8000)
                except Exception:
                    pass  # nothing rendered — still try to parse what we have
                clicks = await _expand_with_more_button(
                    page, ["See more", "Show more", "More results"])
                if clicks:
                    logger.debug('Bing Shopping: clicked "see more" %d time(s)', clicks)
                html = await page.content()
            finally:
                await browser.close()
    except Exception as exc:
        logger.debug('Bing Shopping browser path failed (%s); falling back to curl', exc)

    if not html:
        html = await _curl_get(url) or ''
    if not html:
        return []

    results = _parse_bing_shopping_html(html, max_results)
    logger.debug('Bing Shopping: %d results for %r', len(results), query[:60])
    return results


async def _duckduckgo_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape DuckDuckGo Shopping tab using Playwright (JS-rendered).

    DDG shopping has no server-rendered endpoint, so we use a headless browser
    with a short timeout. Returns empty list on failure rather than raising.
    """
    try:
        from playwright.async_api import async_playwright

        q = quote_plus(query)
        url = f"https://duckduckgo.com/?q={q}&ia=shopping&iax=shopping"
        results: List[Dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=_BROWSER_UA)
            page = await ctx.new_page()
            try:
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                # Wait for shopping results to appear (or timeout)
                try:
                    await page.wait_for_selector('[data-testid="shopping-result"], .js-shopping-result, .tile--shopping', timeout=8000)
                except Exception:
                    pass  # No shopping results loaded — still try to parse

                clicks = await _expand_with_more_button(
                    page, ["More results", "See more", "Show more", "More"])
                if clicks:
                    logger.debug('DDG Shopping: clicked "more" %d time(s)', clicks)

                html = await page.content()
            finally:
                await browser.close()

        seen: set = set()
        # DDG shopping cards typically contain product links with prices
        # Try multiple selector patterns across DDG versions
        for link_m in re.finditer(
            r'href="(https?://[^"]+)"[^>]*>[^<]*<[^>]+>[^<]*</[^>]+>\s*[^<]*(\$[\d,.]+)',
            html
        ):
            merchant_url, price_str = link_m.group(1), link_m.group(2)
            domain = _domain(merchant_url)
            if not domain or domain in _NOISE_DOMAINS or merchant_url in seen or 'duckduckgo' in domain:
                continue
            seen.add(merchant_url)
            results.append({
                'href': merchant_url, 'url': merchant_url, 'domain': domain,
                'title': domain,
                'body': price_str,
                'price': price_str,
                'source': 'ddg_shopping',
            })
            if len(results) >= max_results:
                break

        # Also try JSON-LD embedded product data
        for script_m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
            try:
                data = json.loads(script_m.group(1))
                if not isinstance(data, dict):
                    continue
                if data.get('@type') in ('Product', 'ItemList', 'Offer'):
                    offers = data.get('offers', {})
                    if isinstance(offers, dict):
                        offers = [offers]
                    for offer in (offers or []):
                        merchant_url = offer.get('url', '')
                        if not merchant_url:
                            continue
                        domain = _domain(merchant_url)
                        if not domain or merchant_url in seen or 'duckduckgo' in domain:
                            continue
                        seen.add(merchant_url)
                        price = offer.get('price') or offer.get('lowPrice')
                        results.append({
                            'href': merchant_url, 'url': merchant_url, 'domain': domain,
                            'title': data.get('name', domain),
                            'body': str(price or ''),
                            'price': str(price) if price else None,
                            'source': 'ddg_shopping',
                        })
            except Exception:
                continue

        logger.debug('DDG Shopping: %d results for %r', len(results), query[:60])
        return results[:max_results]
    except Exception as exc:
        logger.debug('DDG Shopping failed: %s', exc)
        return []


async def _yahoo_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Walmart search via __NEXT_DATA__ JSON (replaces Yahoo Shopping which is JS-only).

    Walmart embeds all search results in a __NEXT_DATA__ blob that is accessible via curl.
    Results map to walmart.com product URLs so they count as one competitor domain.
    """
    try:
        import json as _json
        q = quote_plus(query)
        base_url = f"https://www.walmart.com/search?q={q}"
        results: List[Dict[str, Any]] = []
        seen_urls: set = set()

        # Page through results (the curl equivalent of clicking "more") until we
        # hit the cap or a page yields no new products.
        for page_num in range(1, _SHOPPING_WALMART_PAGES + 1):
            page_url = base_url if page_num == 1 else f"{base_url}&page={page_num}"
            html = await _curl_get(page_url)
            if not html:
                break

            nd_m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL | re.I)
            if not nd_m:
                break

            nd = _json.loads(nd_m.group(1))
            stacks = (
                nd.get('props', {})
                .get('pageProps', {})
                .get('initialData', {})
                .get('searchResult', {})
                .get('itemStacks', [])
            )
            before = len(results)
            for stack in stacks:
                for item in stack.get('items', []):
                    canon = item.get('canonicalUrl', '')
                    if not canon:
                        continue
                    href = f"https://www.walmart.com{canon.split('?')[0]}"
                    if href in seen_urls:
                        continue
                    price_raw = item.get('price')
                    if not price_raw:
                        price_raw = (item.get('priceInfo') or {}).get('currentPrice', '')
                    price_str = f"${float(price_raw):,.2f}" if price_raw else None
                    seen_urls.add(href)
                    results.append({
                        'href': href, 'url': href, 'domain': 'walmart.com',
                        'title': item.get('name', '')[:200],
                        'body': price_str or '',
                        'price': price_str,
                        'source': 'yahoo_shopping',
                    })
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
            if len(results) >= max_results or len(results) == before:
                break  # cap reached, or this page added nothing new → stop paging

        logger.debug('Walmart Shopping: %d results for %r', len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug('Walmart Shopping failed: %s', exc)
        return []


def _parse_site_search_results(html: str, base_domain: str) -> List[Dict[str, Any]]:
    """Extract product cards from a competitor site's search-results page."""
    clean = re.sub(r'<(?:script|style)[^>]*>.*?</(?:script|style)>', ' ', html,
                   flags=re.DOTALL | re.I)
    results: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for m in re.finditer(r'<a\b[^>]+href="([^"#][^"]*)"[^>]*>(.*?)</a>', clean,
                         re.DOTALL | re.I):
        raw_href = m.group(1).strip()
        link_text = re.sub(r'<[^>]+>', ' ', m.group(2))
        link_text = re.sub(r'\s+', ' ', link_text).strip()
        if len(link_text) < 4:
            continue
        if any(s in raw_href.lower() for s in _SITE_SKIP_HREFS):
            continue

        if raw_href.startswith('http'):
            href = raw_href
        elif raw_href.startswith('/'):
            href = f'https://{base_domain}{raw_href}'
        else:
            continue

        if _domain(href) != base_domain:
            continue
        if href in seen_urls:
            continue

        ctx = clean[max(0, m.start() - 50): m.end() + 400]
        price_m = _PRICE_RE.search(ctx)
        if not price_m:
            continue

        seen_urls.add(href)
        plain_ctx = re.sub(r'<[^>]+>', ' ', ctx)
        plain_ctx = re.sub(r'\s+', ' ', plain_ctx).strip()

        results.append({
            'url': href,
            'domain': base_domain,
            'title': link_text[:200],
            'description': plain_ctx[:300],
            'price': price_m.group(0).strip(),
            'model_number': _extract_model(plain_ctx),
        })
        if len(results) >= 25:
            break

    return results


async def _search_competitor_site(
    domain: str,
    query: str,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """Try common search URL patterns against a competitor site and return product hits."""
    q = quote_plus(query)
    base = f'https://{domain}'

    for pattern in _SITE_SEARCH_PATTERNS:
        url = base + pattern.format(q=q)
        try:
            # Probe each candidate URL once (retries=1) with a tight timeout: a dead
            # or wrong pattern should fail fast and let the next pattern try, rather
            # than paying 3× retry latency across 10 patterns × hundreds of domains.
            html = await _curl_get(url, timeout=5, retries=1)
        except Exception:
            continue
        if not html or len(html) < 300:
            continue
        if not _PRICE_RE.search(html):
            continue
        results = _parse_site_search_results(html, domain)
        if results:
            logger.debug("Site search: %s query=%r → %d hits via %s",
                         domain, query[:40], len(results), pattern)
            return results[:max_results]

    return []


# Costco, Sam's Club and Uber Eats sit behind aggressive anti-bot protection
# (Akamai / PerimeterX) that blocks curl *and* a headless browser outright. We
# reach their products through Google's index via SerpAPI instead: a
# `site:<domain>` query returns real product/store pages on that domain (title,
# URL, and price when Google surfaces it in the result's rich snippet). URL
# substrings that mark an actual product/store page (vs. a category landing page)
# are preferred so the better hits sort first.
_RETAILER_PRODUCT_HINTS = {
    'costco.com':   ('.product.', '/p/', '.html'),
    'samsclub.com': ('/ip/',),
    'ubereats.com': ('/store/',),
}


async def _serpapi_site_search(
    domain: str, query: str, max_results: int, source_key: str,
) -> List[Dict[str, Any]]:
    """Return products from a bot-protected retailer via a SerpAPI ``site:`` Google
    search. Product-page URLs are preferred; if too few are found, category/landing
    pages backfill so the engine still returns something. Returns [] when no SerpAPI
    key is configured or on any error, exactly like any other engine."""
    from backend.config import Config
    api_key = (Config().get('serpapi', 'api_key') or '').strip()
    if not api_key:
        return []
    try:
        import json as _json
        q = quote_plus(f"{query} site:{domain}")
        url = (
            f"https://serpapi.com/search.json?engine=google&q={q}"
            f"&api_key={api_key}&num=20&gl=us&hl=en"
        )
        raw = await _curl_get(url, timeout=20)
        if not raw:
            return []
        org = _json.loads(raw).get('organic_results', []) or []

        hints = _RETAILER_PRODUCT_HINTS.get(domain, ())
        primary: List[Dict[str, Any]] = []   # actual product/store pages
        secondary: List[Dict[str, Any]] = [] # category/landing pages (backfill)
        seen: set = set()
        for r in org:
            href = r.get('link', '')
            if not href or href in seen:
                continue
            d = _domain(href)
            if not d or domain not in d:
                continue
            seen.add(href)

            title = (r.get('title') or '')[:200]
            snippet = r.get('snippet') or ''

            # Price: SerpAPI's rich-snippet extension first, then any $-price in text.
            price = None
            det = ((r.get('rich_snippet') or {}).get('top') or {}).get('detected_extensions') or {}
            if det.get('price'):
                price = f"{det.get('currency') or '$'}{det['price']}"
            if not price:
                pm = _PRICE_RE.search(f"{title} {snippet}")
                if pm:
                    price = pm.group(0).strip()

            item = {
                'href': href, 'url': href, 'domain': d,
                'title': title or d,
                'body': snippet[:300],
                'price': price,
                'source': source_key,
            }
            (primary if (hints and any(h in href for h in hints)) else secondary).append(item)

        results = primary if len(primary) >= 3 else primary + secondary
        logger.debug('%s site search: %d results (%d product pages) for %r',
                     domain, len(results), len(primary), query[:60])
        return results[:max_results]
    except Exception as exc:
        logger.debug('%s SerpAPI site search failed: %s', domain, exc)
        return []


# Bright Data Web Unlocker gets past the Akamai/PerimeterX walls on Costco and
# Sam's Club, returning the real search-results HTML (with live prices). Configured
# via config/settings.yaml -> brightdata: {api_token, zone}. When unconfigured or
# erroring, the retailer engines fall back to the SerpAPI `site:` path.
_BRIGHTDATA_SEARCH_URLS = {
    'costco.com':   'https://www.costco.com/CatalogSearch?keyword={q}',
    'samsclub.com': 'https://www.samsclub.com/s/{q}',
}


async def _brightdata_fetch(url: str) -> str:
    """Fetch a URL through the Bright Data Web Unlocker API. Returns the unblocked
    page HTML, or '' when no brightdata credentials are configured / on error."""
    from backend.config import Config
    cfg = Config()
    token = (cfg.get('brightdata', 'api_token') or '').strip()
    zone = (cfg.get('brightdata', 'zone') or '').strip()
    if not token or not zone:
        return ''
    try:
        html = await _curl_post(
            'https://api.brightdata.com/request',
            json_body={'zone': zone, 'url': url, 'format': 'raw', 'country': 'us'},
            extra_headers=[
                f'Authorization: Bearer {token}',
                'Content-Type: application/json',
            ],
            timeout=90,
        )
        return html or ''
    except Exception as exc:
        logger.debug('Bright Data fetch failed for %s: %s', url, exc)
        return ''


def _extract_jsonld_products(html: str, domain: str) -> List[Dict[str, Any]]:
    """Pull Product/Offer entries out of JSON-LD blocks — a reliable price source on
    retailer pages that embed structured data. Best-effort; skips anything malformed."""
    out: List[Dict[str, Any]] = []

    def _consume(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                _consume(n)
            return
        if not isinstance(node, dict):
            return
        graph = node.get('@graph')
        if isinstance(graph, list):
            for n in graph:
                _consume(n)
        types = node.get('@type')
        types = types if isinstance(types, list) else [types]
        if 'Product' in types:
            offers = node.get('offers') or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = (offers or {}).get('price') or (offers or {}).get('lowPrice')
            url = node.get('url') or (offers or {}).get('url') or ''
            if url and not url.startswith('http'):
                url = f'https://{domain}{url}'
            if url and _domain(url) == domain:
                out.append({
                    'url': url, 'domain': domain,
                    'title': (node.get('name') or '')[:200],
                    'description': (node.get('description') or '')[:300],
                    'price': f"${price}" if price else None,
                })

    for m in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL | re.I
    ):
        try:
            _consume(json.loads(m.group(1).strip()))
        except Exception:
            continue
    return out


async def _brightdata_retailer_search(
    domain: str, query: str, max_results: int, source_key: str,
) -> List[Dict[str, Any]]:
    """Search a bot-protected retailer's own site via Bright Data Web Unlocker, parsing
    products (with live prices) from the returned HTML. Returns [] if not configured
    or nothing parses, so callers can fall back to the SerpAPI `site:` path."""
    tmpl = _BRIGHTDATA_SEARCH_URLS.get(domain)
    if not tmpl:
        return []
    try:
        html = await _brightdata_fetch(tmpl.format(q=quote_plus(query)))
        if not html or len(html) < 500:
            return []

        # Strategy 1: generic anchor-near-price parsing (same as competitor sites).
        results = _parse_site_search_results(html, domain)
        # Strategy 2: JSON-LD products — merge in, deduped by URL.
        seen = {r.get('url') for r in results}
        for p in _extract_jsonld_products(html, domain):
            if p['url'] not in seen:
                seen.add(p['url'])
                results.append(p)

        for r in results:
            r['href'] = r.get('href') or r.get('url')
            r['source'] = source_key
        logger.info('Bright Data %s: %d results for %r', domain, len(results), query[:60])
        return results[:max_results]
    except Exception as exc:
        logger.debug('Bright Data %s search failed: %s', domain, exc)
        return []


async def _costco_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Search Costco — Bright Data Web Unlocker first (live prices), SerpAPI `site:` fallback."""
    res = await _brightdata_retailer_search('costco.com', query, max_results, 'costco')
    if res:
        return res
    return await _serpapi_site_search('costco.com', query, max_results, 'costco')


async def _samsclub_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Search Sam's Club — Bright Data Web Unlocker first (live prices), SerpAPI `site:` fallback."""
    res = await _brightdata_retailer_search('samsclub.com', query, max_results, 'samsclub')
    if res:
        return res
    return await _serpapi_site_search('samsclub.com', query, max_results, 'samsclub')


async def _ubereats_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Search Uber Eats stores (via SerpAPI site search — Uber Eats blocks scraping)."""
    return await _serpapi_site_search('ubereats.com', query, max_results, 'ubereats')
