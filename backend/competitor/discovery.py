"""
Competitor Discovery (F12-F13, F16, F69)
Finds competitor websites via Bing HTML search using httpx (no JS rendering needed).
"""
import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

EXCLUDED_DOMAINS = {
    "donut-supplies.com",
    "donut-equipment.com",
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
    "duckduckgo.com",
    "microsoft.com",
    "yellowpages.com",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
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


def _is_excluded(domain: str) -> bool:
    if not domain:
        return True
    for excl in EXCLUDED_DOMAINS:
        if domain == excl or domain.endswith("." + excl):
            return True
    return False


async def _bing_search(query: str, max_per_query: int = 10) -> list[tuple[str, str]]:
    """
    Returns (url, title) pairs from Bing's plain HTML search endpoint.
    Bing result links appear as <h2><a href="https://...">Title</a></h2>
    inside <li class="b_algo"> elements.
    """
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
        resp = await client.get(
            "https://www.bing.com/search",
            params={"q": query, "count": "20"},
        )
        resp.raise_for_status()

    html = resp.text
    results: list[tuple[str, str]] = []

    # Each organic result block: <li class="b_algo">...<h2><a href="URL">Title</a></h2>
    for block in re.finditer(r'class="b_algo".*?</li>', html, re.DOTALL):
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)', block.group())
        if not m:
            continue
        url = m.group(1)
        title = m.group(2).strip()
        results.append((url, title))
        if len(results) >= max_per_query:
            break

    return results


async def discover_competitors(
    queries: List[str],
    max_results: int = 20,
    already_known: Optional[set] = None,
    progress_cb=None,
) -> List[dict]:
    """
    Search Bing for competitor sites using the given queries.
    Returns list of dicts: {domain, name, base_url, discovered_via}.
    """
    known = already_known or set()
    found: dict[str, dict] = {}

    for query in queries:
        if len(found) >= max_results:
            break
        try:
            hits = await _bing_search(query, max_per_query=15)

            for url, title in hits:
                if len(found) >= max_results:
                    break
                domain = _extract_domain(url)
                if not domain or _is_excluded(domain) or domain in known or domain in found:
                    continue
                found[domain] = {
                    "domain": domain,
                    "name": title[:100] if title else domain,
                    "base_url": f"https://{domain}",
                    "discovered_via": query,
                }
                if progress_cb:
                    await progress_cb("competitor_found", {"domain": domain, "total": len(found)})

            logger.info("Query %r: %d hits from Bing, %d total competitors so far", query, len(hits), len(found))
        except Exception as exc:
            logger.warning("Discovery query failed: %r — %s", query, exc)

    return list(found.values())[:max_results]


async def bulk_import_competitors(domains: List[str]) -> List[dict]:
    """F69: Parse a user-supplied list of domain URLs and return structured dicts."""
    results = []
    for raw in domains:
        raw = raw.strip()
        if not raw:
            continue
        if not raw.startswith("http"):
            raw = "https://" + raw
        domain = _extract_domain(raw)
        if domain and not _is_excluded(domain):
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

    for model in model_numbers[:5]:
        if model and len(model) > 3:
            queries.append(f'"{model}" buy price')

    for mfr in manufacturers[:5]:
        if mfr:
            queries.append(f'"{mfr}" donut equipment dealer')

    queries.extend(industry_terms)

    if custom_keywords:
        queries.extend(custom_keywords)

    return queries[:20]
