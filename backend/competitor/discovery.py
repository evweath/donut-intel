"""
Competitor Discovery (F12-F13, F16, F69)
Finds competitor websites via multi-engine web search.
"""
import logging
from typing import List, Optional
from urllib.parse import urlparse

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


async def discover_competitors(
    queries: List[str],
    max_results: int = 20,
    already_known: Optional[set] = None,
    progress_cb=None,
) -> List[dict]:
    """
    Search for competitor sites using the given queries via multi-engine search.
    Returns list of dicts: {domain, name, base_url, discovered_via}.
    """
    from backend.search.engine import multi_engine_search

    known = already_known or set()
    found: dict[str, dict] = {}

    for query in queries:
        if len(found) >= max_results:
            break
        try:
            hits = await multi_engine_search(query, max_results=15, log_label="competitor discovery")

            for item in hits:
                if len(found) >= max_results:
                    break
                url = item.get('href') or item.get('url', '')
                title = item.get('title', '')
                domain = _extract_domain(url) if url else None
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

            logger.info("Query %r: %d hits, %d total competitors so far", query, len(hits), len(found))
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
