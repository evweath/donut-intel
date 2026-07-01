"""
Parsing primitives shared across every search engine adapter and page module:
URL/domain handling, price/model extraction, and the image-domain index.

These are page-agnostic. Per-page modules must import from here rather than keep
their own copies — divergent copies are how price/model extraction silently drifts.
"""
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# Capturing group 1 = the numeric portion (no '$'). group(0) still includes '$',
# so _extract_price (display string) and _extract_price_float (numeric) share it.
_PRICE_RE = re.compile(r'\$\s*([\d,]+(?:\.\d{1,2})?)')
_MODEL_RE = re.compile(
    r'(?:model|model\s*#|model\s*no|part\s*#|sku|item\s*#)[:\s#]+([A-Z0-9][\w\-/]{2,})', re.I
)


def _domain(url: str) -> str:
    """Return the host with a leading 'www.' removed.

    NOTE: must NOT use lstrip('www.') — str.lstrip strips any leading chars in
    the set {w, .}, so 'www.walmart.com' became 'almart.com' and
    'www.webstaurantstore.com' became 'ebstaurantstore.com' (both major
    competitors). Strip only the literal 'www.' prefix.
    """
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ''


# Country-code TLDs treated as NON-US (used by the "USA websites only" filter).
# Deliberately EXCLUDES generically-used ccTLDs (.co, .io, .ai, .me, .tv, .cc) to
# avoid dropping US sites that use them. '.us' is always US.
_FOREIGN_CCTLDS = frozenset({
    'uk', 'gb', 'ca', 'au', 'nz', 'ie', 'de', 'fr', 'es', 'it', 'nl', 'be', 'ch',
    'at', 'se', 'no', 'fi', 'dk', 'is', 'pt', 'gr', 'lu', 'pl', 'cz', 'sk', 'hu',
    'ro', 'bg', 'hr', 'si', 'rs', 'lt', 'lv', 'ee', 'ru', 'ua', 'by', 'tr', 'in',
    'pk', 'bd', 'lk', 'np', 'cn', 'jp', 'kr', 'hk', 'tw', 'sg', 'my', 'th', 'id',
    'ph', 'vn', 'kh', 'mx', 'br', 'ar', 'cl', 'pe', 'uy', 'py', 've', 'ec', 'bo',
    'za', 'ng', 'ke', 'gh', 'eg', 'ma', 'dz', 'tn', 'ae', 'sa', 'qa', 'kw', 'bh',
    'om', 'jo', 'lb', 'il', 'ir', 'iq',
})


def is_usa_domain(domain: str) -> bool:
    """Heuristic: True unless the domain uses a non-US country-code TLD.

    Offline and TLD-based — a generic TLD (.com/.net/.org/.us/...) passes; a
    foreign ccTLD (.co.uk, .ca, .com.au, .de, .cn) is rejected. A '.com' hosted
    abroad still passes (no geo-IP lookup). See "USA websites only" search filter.
    """
    d = (domain or '').strip().lower().rstrip('.')
    if not d:
        return False
    if d.endswith('.us'):
        return True
    tld = d.rsplit('.', 1)[-1]
    return tld not in _FOREIGN_CCTLDS


def filter_usa_domains(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop result rows whose 'domain' is a non-US country-code TLD."""
    return [r for r in results if is_usa_domain(r.get('domain') or '')]


def _is_homepage(url: str) -> bool:
    """Return True if the URL is a bare domain homepage with no meaningful path."""
    try:
        path = urlparse(url).path
        return not path or path == '/'
    except Exception:
        return False


def _extract_price(text: str) -> Optional[str]:
    """Display form — returns the matched price including '$' (e.g. '$49.99')."""
    m = _PRICE_RE.search(text or '')
    return m.group(0).strip() if m else None


def _extract_price_float(text: str) -> Optional[float]:
    """Numeric form — returns the price as a float (e.g. 49.99) for DB storage.

    Distinct from _extract_price (str) on purpose: callers that persist or compare
    prices need a number, callers that render need the '$'-prefixed string.
    """
    m = _PRICE_RE.search(text or '')
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            pass
    return None


def _extract_model(text: str) -> Optional[str]:
    m = _MODEL_RE.search(text or '')
    return m.group(1).strip() if m else None


def _img_index(images: List[Dict]) -> Dict[str, str]:
    """Build domain → image-url index from DDG image results."""
    idx: Dict[str, str] = {}
    for img in images:
        d = _domain(img.get('url', ''))
        if d and d not in idx:
            idx[d] = img.get('image') or img.get('thumbnail', '')
    return idx


def _cite_to_url(cite_html: str) -> str:
    """Convert a Bing display URL (with › separators) into a real URL."""
    text = re.sub(r'<[^>]+>', '', cite_html).strip()
    text = text.replace(' › ', '/').replace('› ', '/').replace(' ›', '/')
    # Strip Bing's display ellipsis — path was truncated, keep only what we have
    text = re.sub(r'[…\.]{2,}\s*$', '', text).rstrip('/')
    if not text.startswith('http'):
        text = 'https://' + text
    return text


# ---------------------------------------------------------------------------
# Product-page extraction — shared by the competitor scan modules.
# These return a dict with keys: title, price (float|None), model_number,
# manufacturer, sku, in_stock, image, description. Unified here so the two scan
# modules can no longer drift (product_search had image+description, the web scan
# did not — that divergence is what this consolidation fixes).
# ---------------------------------------------------------------------------

def _parse_jsonld(html: str) -> Optional[Dict[str, Any]]:
    """Extract the first schema.org/Product from JSON-LD blocks."""
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.I
    ):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and '@graph' in data:
            items = data['@graph']
        for item in items:
            if not isinstance(item, dict):
                continue
            type_val = item.get('@type', '')
            if 'Product' not in (type_val if isinstance(type_val, str) else ' '.join(type_val)):
                continue
            price: Optional[float] = None
            offers = item.get('offers', {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                raw_price = offers.get('price') or offers.get('lowPrice')
                if raw_price is not None:
                    try:
                        price = float(str(raw_price).replace(',', '').replace('$', ''))
                    except ValueError:
                        pass
            brand = item.get('brand', {})
            manufacturer = brand.get('name') if isinstance(brand, dict) else (brand or None)
            in_stock = 'InStock' in json.dumps(item.get('offers', ''))

            image_raw = item.get('image')
            if isinstance(image_raw, list):
                image_raw = image_raw[0] if image_raw else None
            if isinstance(image_raw, dict):
                image_url = image_raw.get('url') or image_raw.get('contentUrl')
            else:
                image_url = image_raw

            desc = item.get('description', '')
            if isinstance(desc, str) and len(desc) > 2000:
                desc = desc[:2000]

            return {
                'title': item.get('name', ''),
                'price': price,
                'model_number': item.get('model') or item.get('mpn'),
                'manufacturer': manufacturer,
                'sku': item.get('sku'),
                'in_stock': in_stock,
                'image': image_url or None,
                'description': desc or None,
            }
    return None


def _meta_val(html: str, prop: str) -> Optional[str]:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\'][^"\']*{re.escape(prop)}[^"\']*["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.I
    )
    if m:
        return m.group(1).strip()
    # alternate attribute order
    m = re.search(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'][^"\']*{re.escape(prop)}[^"\']*["\']',
        html, re.I
    )
    return m.group(1).strip() if m else None


def _parse_meta(html: str) -> Dict[str, Any]:
    """Fallback: extract product info from meta / OG / title tags."""
    title_tag = re.search(r'<title[^>]*>([^<]{1,300})</title>', html, re.I)
    title = _meta_val(html, 'og:title') or _meta_val(html, 'title') or (title_tag.group(1).strip() if title_tag else '')
    price_str = (
        _meta_val(html, 'price:amount') or _meta_val(html, 'og:price:amount') or
        _meta_val(html, 'product:price:amount') or _meta_val(html, 'price')
    )
    price: Optional[float] = None
    if price_str:
        try:
            price = float(re.sub(r'[^\d.]', '', price_str))
        except ValueError:
            pass
    if price is None:
        price = _extract_price_float(html[:8000])
    return {
        'title': title or '',
        'price': price,
        'model_number': _meta_val(html, 'model') or _meta_val(html, 'mpn'),
        'manufacturer': _meta_val(html, 'og:brand') or _meta_val(html, 'brand'),
        'sku': _meta_val(html, 'sku') or _meta_val(html, 'product:retailer_item_id'),
        'in_stock': True,
        'image': _meta_val(html, 'og:image') or _meta_val(html, 'twitter:image'),
        'description': _meta_val(html, 'og:description') or _meta_val(html, 'description'),
    }
