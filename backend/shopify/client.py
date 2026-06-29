"""
Shopify Admin REST API client.
Handles authentication, pagination (cursor-based Link headers), and
light rate-limit back-off (leaky bucket: 40 calls / 2 per second).
"""
import asyncio
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from . import connlog

logger = logging.getLogger(__name__)

_API_VERSION = "2024-01"

# Shopify returns 403 with a body like
#   {"errors":"[API] This action requires merchant approval for read_products scope."}
# when the app's token is valid but the merchant never granted that access scope.
_SCOPE_APPROVAL_RE = re.compile(r"requires merchant approval for (\w+) scope", re.IGNORECASE)


def missing_scope(status: int, body: Optional[str]) -> Optional[str]:
    """Return the un-granted Admin API scope name (e.g. ``read_products``) if a
    Shopify error is a 403 'requires merchant approval for X scope', else None.

    Used to turn an opaque 403 into an actionable "enable this scope" message.
    Only 403s mean a scope-approval problem — a 401/429 with similar wording is
    something else, so status is checked first.
    """
    if status != 403:
        return None
    m = _SCOPE_APPROVAL_RE.search(body or "")
    return m.group(1) if m else None


def _host_of(store_url: str) -> str:
    """Extract a bare host (no scheme/path) for connection-log messages."""
    u = (store_url or "").strip().rstrip("/")
    u = re.sub(r"^https?://", "", u)
    return u.split("/")[0] or "(unknown)"


# Transient connection-layer errors worth retrying. These occur when the network
# path flaps (VPN/firewall/egress filtering) — the request never reached Shopify,
# so a retry a moment later usually succeeds. HTTP 4xx/5xx responses are NOT here:
# those mean Shopify answered, and retrying blindly would be wrong.
_TRANSIENT_CONN_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)
_CONNECT_RETRIES = 4
_CONNECT_BACKOFF_BASE = 0.6  # seconds: 0.6, 1.2, 2.4, 4.8


async def _with_connect_retry(make_request, *, host: str, label: str):
    """Run an httpx request, retrying transient connection failures with backoff.

    make_request is a zero-arg callable returning the request awaitable, so each
    retry issues a fresh request. Raises the last transient error if all attempts
    fail. Non-transient exceptions (and HTTP error responses) propagate immediately.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(_CONNECT_RETRIES):
        try:
            return await make_request()
        except _TRANSIENT_CONN_ERRORS as exc:
            last_exc = exc
            if attempt + 1 >= _CONNECT_RETRIES:
                break
            wait = _CONNECT_BACKOFF_BASE * (2 ** attempt)
            connlog.record(
                f"… {label} {host}: {type(exc).__name__} — retry {attempt + 1}/{_CONNECT_RETRIES} in {wait:.1f}s"
            )
            await asyncio.sleep(wait)
    connlog.record(
        f"✗ {label} {host}: connection failed after {_CONNECT_RETRIES} attempts "
        f"({type(last_exc).__name__}: {last_exc})",
        level="error",
    )
    raise last_exc  # type: ignore[misc]


async def fetch_access_token(store_url: str, client_id: str, client_secret: str) -> str:
    """Exchange client_id + client_secret for a short-lived Admin API access token (~24h)."""
    url = store_url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    host = _host_of(url)
    connlog.record(f"→ Auth: requesting access token from {host}")
    timeout = httpx.Timeout(connect=10.0, read=15.0, write=15.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        resp = await _with_connect_retry(
            lambda: http.post(
                f"{url}/admin/oauth/access_token",
                data={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ),
            host=host, label="Auth",
        )
    if resp.status_code >= 400:
        connlog.record(f"✗ Auth: {host} returned {resp.status_code} {resp.text[:120]}", level="error")
        raise ShopifyError(resp.status_code, resp.text)
    data = resp.json()
    # Shopify returns the scopes ACTUALLY granted to this token in `scope`. This is
    # the ground truth — it can differ from what the app's config screen shows if the
    # app wasn't (re)installed after scopes changed, or the creds point at a different
    # app. Log it (scopes aren't secret) so the Connection Log panel reveals exactly
    # what the token can do, e.g. a missing read_products explains a later 403.
    granted = data.get("scope") or data.get("associated_user_scope") or ""
    connlog.record(f"✓ Auth: token from {host} — granted scopes: {granted or '(none reported)'}")
    return data["access_token"]


class ShopifyError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Shopify API {status}: {body[:300]}")

    @property
    def missing_scope(self) -> Optional[str]:
        """The un-granted Admin API scope, if this is a 403 scope-approval error."""
        return missing_scope(self.status, self.body)


class ShopifyClient:
    def __init__(self, store_url: str, access_token: str):
        url = store_url.strip().rstrip("/")
        if not url.startswith("http"):
            url = "https://" + url
        self.base = f"{url}/admin/api/{_API_VERSION}"
        self._host = _host_of(url)
        self._headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
        self._client = httpx.AsyncClient(headers=self._headers, timeout=timeout)
        connlog.record(f"→ Opening session to {self._host}")
        return self

    async def __aexit__(self, *_):
        if self._client:
            await self._client.aclose()

    async def _get(self, path: str, params: Optional[Dict] = None) -> httpx.Response:
        assert self._client, "Use as async context manager"
        for attempt in range(4):
            resp = await _with_connect_retry(
                lambda: self._client.get(f"{self.base}{path}", params=params),
                host=self._host, label=f"GET {path}",
            )
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                connlog.record(f"… Rate limited by {self._host} — retrying in {retry_after:.1f}s")
                logger.debug("Shopify rate limit — sleeping %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code >= 400:
                connlog.record(f"✗ GET {self._host}{path} → {resp.status_code}", level="error")
                raise ShopifyError(resp.status_code, resp.text)
            return resp
        connlog.record(f"✗ GET {self._host}{path} → rate limited after retries", level="error")
        raise ShopifyError(429, "Rate limited after retries")

    async def _post(self, path: str, data: Dict) -> Dict:
        assert self._client
        for attempt in range(4):
            resp = await _with_connect_retry(
                lambda: self._client.post(f"{self.base}{path}", json=data),
                host=self._host, label=f"POST {path}",
            )
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                connlog.record(f"✗ POST {self._host}{path} → {resp.status_code}", level="error")
                raise ShopifyError(resp.status_code, resp.text)
            return resp.json()
        raise ShopifyError(429, "Rate limited")

    async def _put(self, path: str, data: Dict) -> Dict:
        assert self._client
        for attempt in range(4):
            resp = await _with_connect_retry(
                lambda: self._client.put(f"{self.base}{path}", json=data),
                host=self._host, label=f"PUT {path}",
            )
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                connlog.record(f"✗ PUT {self._host}{path} → {resp.status_code}", level="error")
                raise ShopifyError(resp.status_code, resp.text)
            return resp.json()
        raise ShopifyError(429, "Rate limited")

    async def _delete(self, path: str) -> None:
        assert self._client
        resp = await _with_connect_retry(
            lambda: self._client.delete(f"{self.base}{path}"),
            host=self._host, label=f"DELETE {path}",
        )
        if resp.status_code == 429:
            await asyncio.sleep(2)
            resp = await _with_connect_retry(
                lambda: self._client.delete(f"{self.base}{path}"),
                host=self._host, label=f"DELETE {path}",
            )
        if resp.status_code not in (200, 204):
            connlog.record(f"✗ DELETE {self._host}{path} → {resp.status_code}", level="error")
            raise ShopifyError(resp.status_code, resp.text)

    def _next_page_info(self, resp: httpx.Response) -> Optional[str]:
        link = resp.headers.get("Link", "")
        m = re.search(r'<[^>]+[?&]page_info=([^&>]+)[^>]*>;\s*rel="next"', link)
        return m.group(1) if m else None

    # -----------------------------------------------------------------------
    # Shop
    # -----------------------------------------------------------------------

    async def get_shop(self) -> Dict:
        resp = await self._get("/shop.json")
        shop = resp.json().get("shop", {})
        name = shop.get("name") or shop.get("myshopify_domain") or self._host
        connlog.record(f"✓ Connected to {self._host} (shop: {name})")
        return shop

    # -----------------------------------------------------------------------
    # Products (cursor-paginated)
    # -----------------------------------------------------------------------

    async def iter_products(self, limit: int = 250, status: str = "active") -> AsyncIterator[Dict]:
        params: Dict[str, Any] = {"limit": limit, "status": status}
        while True:
            resp = await self._get("/products.json", params=params)
            for p in resp.json().get("products", []):
                yield p
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": limit, "page_info": page_info}

    async def get_product(self, product_id: int) -> Dict:
        resp = await self._get(f"/products/{product_id}.json")
        return resp.json().get("product", {})

    async def create_product(self, data: Dict) -> Dict:
        result = await self._post("/products.json", {"product": data})
        return result.get("product", {})

    async def update_product(self, product_id: int, data: Dict) -> Dict:
        result = await self._put(f"/products/{product_id}.json", {"product": data})
        return result.get("product", {})

    # -----------------------------------------------------------------------
    # Collections
    # -----------------------------------------------------------------------

    async def get_custom_collections(self) -> List[Dict]:
        collections = []
        params: Dict[str, Any] = {"limit": 250}
        while True:
            resp = await self._get("/custom_collections.json", params=params)
            batch = resp.json().get("custom_collections", [])
            collections.extend(batch)
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": 250, "page_info": page_info}
        return collections

    async def get_smart_collections(self) -> List[Dict]:
        collections = []
        params: Dict[str, Any] = {"limit": 250}
        while True:
            resp = await self._get("/smart_collections.json", params=params)
            batch = resp.json().get("smart_collections", [])
            collections.extend(batch)
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": 250, "page_info": page_info}
        return collections

    async def get_collects(self, collection_id: Optional[int] = None) -> List[Dict]:
        """Return product↔collection membership records."""
        collects = []
        params: Dict[str, Any] = {"limit": 250}
        if collection_id:
            params["collection_id"] = collection_id
        while True:
            resp = await self._get("/collects.json", params=params)
            batch = resp.json().get("collects", [])
            collects.extend(batch)
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": 250, "page_info": page_info}
        return collects

    async def add_to_collection(self, collection_id: int, product_id: int) -> Dict:
        result = await self._post("/collects.json", {
            "collect": {"collection_id": collection_id, "product_id": product_id}
        })
        return result.get("collect", {})

    async def remove_from_collection(self, collect_id: int) -> None:
        await self._delete(f"/collects/{collect_id}.json")

    # -----------------------------------------------------------------------
    # Metafields
    # -----------------------------------------------------------------------

    async def get_product_metafields(self, product_id: int) -> List[Dict]:
        resp = await self._get(f"/products/{product_id}/metafields.json")
        return resp.json().get("metafields", [])

    async def set_product_metafield(self, product_id: int, namespace: str,
                                    key: str, value: str, value_type: str = "string") -> Dict:
        result = await self._post(f"/products/{product_id}/metafields.json", {
            "metafield": {"namespace": namespace, "key": key,
                          "value": value, "type": value_type}
        })
        return result.get("metafield", {})

    # -----------------------------------------------------------------------
    # Webhooks
    # -----------------------------------------------------------------------

    async def list_webhooks(self) -> List[Dict]:
        """Return all webhook subscriptions registered in this store."""
        webhooks: List[Dict] = []
        params: Dict[str, Any] = {"limit": 250}
        while True:
            resp = await self._get("/webhooks.json", params=params)
            batch = resp.json().get("webhooks", [])
            webhooks.extend(batch)
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": 250, "page_info": page_info}
        return webhooks

    async def create_webhook(self, topic: str, address: str, format: str = "json") -> Dict:
        """Register a new webhook subscription."""
        result = await self._post("/webhooks.json", {
            "webhook": {"topic": topic, "address": address, "format": format}
        })
        return result.get("webhook", {})

    async def delete_webhook(self, webhook_id: int) -> None:
        """Delete a webhook subscription by its Shopify ID."""
        await self._delete(f"/webhooks/{webhook_id}.json")
