"""
Web search engine for Find This Product, Beat This Price, Find Me Customers.
Uses DuckDuckGo (no API key required).
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r'\$\s*[\d,]+(?:\.\d{1,2})?')
_MODEL_RE = re.compile(
    r'(?:model|model\s*#|model\s*no|part\s*#|sku|item\s*#)[:\s#]+([A-Z0-9][\w\-/]{2,})', re.I
)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip('www.')
    except Exception:
        return ''


def _extract_price(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text or '')
    return m.group(0).strip() if m else None


def _extract_model(text: str) -> Optional[str]:
    m = _MODEL_RE.search(text or '')
    return m.group(1).strip() if m else None


async def _run_sync(fn):
    return await asyncio.get_event_loop().run_in_executor(None, fn)


async def _text_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    def _search():
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results, backend='duckduckgo'))
    try:
        return await _run_sync(_search)
    except Exception as exc:
        logger.error(f"DDG text search failed: {exc}")
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


def _img_index(images: List[Dict]) -> Dict[str, str]:
    """Build domain → image-url index from DDG image results."""
    idx: Dict[str, str] = {}
    for img in images:
        d = _domain(img.get('url', ''))
        if d and d not in idx:
            idx[d] = img.get('image') or img.get('thumbnail', '')
    return idx


async def find_products(
    query: str,
    exclude_domains: Optional[set] = None,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Search the web for products matching query; exclude known competitor domains."""
    product_query = f"{query} buy price"
    texts, images = await asyncio.gather(
        _text_search(product_query, max_results=max_results * 4),
        _image_search(product_query, max_results=max_results * 4),
    )
    img_idx = _img_index(images)
    exclude = exclude_domains or set()
    results: List[Dict] = []
    for item in texts:
        url = item.get('href', '')
        domain = _domain(url)
        if not domain or domain in exclude:
            continue
        snippet = item.get('body', '')
        results.append({
            'url': url,
            'domain': domain,
            'title': item.get('title', ''),
            'description': snippet,
            'price': _extract_price(snippet),
            'model_number': _extract_model(snippet),
            'image': img_idx.get(domain, ''),
        })
        if len(results) >= max_results:
            break
    return results


async def find_suppliers(
    description: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    characteristics: Optional[Dict] = None,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """Find alternate suppliers and prices for a product description."""
    parts = [description]
    if price_max:
        parts.append(f"under ${price_max:.0f}")
    elif price_min:
        parts.append(f"over ${price_min:.0f}")
    if characteristics:
        for v in characteristics.values():
            if v:
                parts.append(str(v))
    parts.append("supplier wholesale price")
    query = ' '.join(parts)

    texts, images = await asyncio.gather(
        _text_search(query, max_results=max_results * 3),
        _image_search(query, max_results=max_results),
    )
    img_idx = _img_index(images)

    results: List[Dict] = []
    seen: set = set()
    for item in texts:
        url = item.get('href', '')
        domain = _domain(url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        snippet = item.get('body', '')
        results.append({
            'url': url,
            'domain': domain,
            'title': item.get('title', ''),
            'description': snippet,
            'price': _extract_price(snippet),
            'model_number': _extract_model(snippet),
            'image': img_idx.get(domain, ''),
        })
        if len(results) >= max_results:
            break
    return results


async def find_customers(
    business_type: Optional[str] = None,
    location: Optional[str] = None,
    radius_miles: Optional[int] = None,
    keywords: Optional[List[str]] = None,
    max_results: int = 20,
) -> List[Dict[str, Any]]:
    """Search for potential customers matching the given profile."""
    parts: List[str] = []
    if business_type:
        parts.append(business_type)
    if location:
        loc_str = f"near {location}" if not radius_miles else f"within {radius_miles} miles of {location}"
        parts.append(loc_str)
    if keywords:
        parts.extend(keywords)
    parts.append("business contact")
    query = ' '.join(parts)

    texts = await _text_search(query, max_results=max_results * 2)

    results: List[Dict] = []
    seen: set = set()
    for item in texts:
        url = item.get('href', '')
        domain = _domain(url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        results.append({
            'url': url,
            'domain': domain,
            'name': item.get('title', ''),
            'description': item.get('body', ''),
        })
        if len(results) >= max_results:
            break
    return results
