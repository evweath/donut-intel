"""
Competitor Discovery (F12-F13, F16, F69)
Finds competitor websites via DuckDuckGo search using Playwright.
"""
import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Domains to exclude (source sites + major marketplaces not worth tracking)
EXCLUDED_DOMAINS = {
    "donut-supplies.com",
    "donut-equipment.com",
    "bakerywholesalers.com",
    "amazon.com",
    "ebay.com",
    "walmart.com",
    "google.com",
    "bing.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "pinterest.com",
    "reddit.com",
    "yelp.com",
    "wikipedia.org",
}


def _extract_domain(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain if domain else None
    except Exception:
        return None


async def discover_competitors(
    queries: List[str],
    max_results: int = 20,
    already_known: Optional[set] = None,
    progress_cb=None,
) -> List[dict]:
    """
    Search DuckDuckGo for competitor sites using the given queries.
    Returns list of dicts: {domain, name, base_url, discovered_via}.
    """
    known = already_known or set()
    found: dict[str, dict] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        for query in queries:
            if len(found) >= max_results:
                break
            try:
                search_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web"
                await page.goto(search_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # Extract result links
                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({href: e.href, text: e.innerText}))"
                )

                for link in links:
                    href = link.get("href", "")
                    text = link.get("text", "").strip()
                    if not href.startswith("http"):
                        continue
                    domain = _extract_domain(href)
                    if not domain:
                        continue
                    if domain in EXCLUDED_DOMAINS or domain in known or domain in found:
                        continue
                    # Skip DuckDuckGo internal links
                    if "duckduckgo.com" in domain:
                        continue
                    found[domain] = {
                        "domain": domain,
                        "name": text[:100] if text else domain,
                        "base_url": f"https://{domain}",
                        "discovered_via": query,
                    }
                    if progress_cb:
                        await progress_cb("competitor_found", {"domain": domain, "total": len(found)})
                    if len(found) >= max_results:
                        break

                logger.info(f"Query '{query}': found {len(found)} total competitors so far")
            except Exception as exc:
                logger.warning(f"Discovery query failed: {query!r} — {exc}")

        await browser.close()

    return list(found.values())[:max_results]


async def bulk_import_competitors(domains: List[str]) -> List[dict]:
    """
    F69: Parse a user-supplied list of domain URLs and return structured dicts.
    """
    results = []
    for raw in domains:
        raw = raw.strip()
        if not raw:
            continue
        if not raw.startswith("http"):
            raw = "https://" + raw
        domain = _extract_domain(raw)
        if domain and domain not in EXCLUDED_DOMAINS:
            results.append({
                "domain": domain,
                "name": domain,
                "base_url": raw,
                "discovered_via": "manual_import",
            })
    return results


def build_discovery_queries(
    product_titles: List[str],
    manufacturers: List[str],
    model_numbers: List[str],
    custom_keywords: Optional[List[str]] = None,
) -> List[str]:
    """Build search queries for competitor discovery."""
    queries = []
    industry_terms = ["donut equipment wholesale", "bakery supply wholesale", "commercial donut fryer"]

    # Model-based queries (highest precision)
    for model in model_numbers[:5]:
        if model and len(model) > 3:
            queries.append(f'"{model}" buy price')

    # Manufacturer + category
    for mfr in manufacturers[:5]:
        if mfr:
            queries.append(f'"{mfr}" donut equipment dealer')

    # Generic industry queries
    queries.extend(industry_terms)

    if custom_keywords:
        queries.extend(custom_keywords)

    return queries[:20]
