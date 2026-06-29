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
from backend.search.core.fetch import _curl_get, _run_sync
from backend.search.core.parse import (
    _PRICE_RE,
    _cite_to_url,
    _domain,
    _extract_model,
    _is_homepage,
)

logger = logging.getLogger(__name__)


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

        if results:
            logger.info("SerpAPI inline shopping: %d results for %r", len(results), query[:60])
            return results

        # Stage 2: google_shopping engine + immersive API for direct store links
        shop_url = (
            f"https://serpapi.com/search.json"
            f"?engine=google_shopping&q={q}&api_key={api_key}&num=20&gl=us&hl=en"
        )
        html2 = await _curl_get(shop_url, timeout=20)
        if not html2:
            return []
        data2 = _json.loads(html2)

        # Concurrently fetch immersive API for up to 8 top products
        imm_items = [
            item for item in data2.get('shopping_results', [])[:8]
            if item.get('serpapi_immersive_product_api')
        ]
        if not imm_items:
            return []
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


async def _bing_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Bing Shopping — merchant URLs are base64-encoded in the u= param of aclick redirects."""
    try:
        q = quote_plus(query)
        url = f"https://www.bing.com/shop?q={q}&count={min(max_results * 2, 40)}&cc=US&setlang=en-US"
        html = await _curl_get(url)
        if not html:
            return []
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
            if not domain or domain in _NOISE_DOMAINS or domain in seen:
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

            seen.add(domain)
            results.append({
                'href': merchant_url, 'url': merchant_url, 'domain': domain,
                'title': title or domain,
                'body': price,
                'price': price or None,
                'source': 'bing_shopping',
            })
            if len(results) >= max_results:
                break

        logger.debug('Bing Shopping: %d results for %r', len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug('Bing Shopping failed: %s', exc)
        return []


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
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await ctx.new_page()
            try:
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                # Wait for shopping results to appear (or timeout)
                try:
                    await page.wait_for_selector('[data-testid="shopping-result"], .js-shopping-result, .tile--shopping', timeout=8000)
                except Exception:
                    pass  # No shopping results loaded — still try to parse

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
            if not domain or domain in _NOISE_DOMAINS or domain in seen or 'duckduckgo' in domain:
                continue
            seen.add(domain)
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
                        if not domain or domain in seen or 'duckduckgo' in domain:
                            continue
                        seen.add(domain)
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
        url = f"https://www.walmart.com/search?q={q}"
        html = await _curl_get(url)
        if not html:
            return []

        nd_m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL | re.I)
        if not nd_m:
            return []

        nd = _json.loads(nd_m.group(1))
        stacks = (
            nd.get('props', {})
            .get('pageProps', {})
            .get('initialData', {})
            .get('searchResult', {})
            .get('itemStacks', [])
        )
        results: List[Dict[str, Any]] = []
        seen_urls: set = set()
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
