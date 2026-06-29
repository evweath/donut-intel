"""
Source site scraper for Donut Intel Platform (F01–F05).
Scrapes the 3 owned source sites and persists products to the database.
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.config import config
from backend.database.db import session_scope
from backend.database.models import (
    Product,
    ProductImage,
    ProductOption,
    ProductSource,
    ScanSession,
)
from backend.competitor.scraper import _is_shopify_store, scrape_shopify_store
from backend.scrapers.base_scraper import BaseScraper, ScrapedProduct

logger = logging.getLogger(__name__)


# Query-string parameters that are pure tracking / collection-position context
# and never identify a distinct product. Stripping them before persisting
# `ProductSource.source_url` prevents the same page (e.g. a Shopify product hit
# from different collection scrolls) from being treated as N different products.
# Values are matched case-insensitively against the parameter name.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {
    # Shopify collection-position telemetry
    "_pos", "_fid", "_ss", "_psq", "_v", "_q",
    # Generic ad/social trackers
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "yclid",
    "ref", "ref_src", "ref_url",
}


def normalize_source_url(url: str) -> str:
    """Canonicalize a product URL for storage + dedupe.

    - Strip tracking query params (`_pos`, `_fid`, `_ss`, `utm_*`, etc.)
    - Strip the URL fragment (`#…`)
    - Drop the leading `www.` so `www.donut-supplies.com` and
      `donut-supplies.com` hash to the same row.
    - Strip a trailing slash on the path so `/products/foo` and `/products/foo/`
      compare equal.
    Real variant params (e.g. `variant=12345`) are preserved.
    """
    if not url:
        return url
    try:
        u = urlparse(url)
    except Exception:
        return url
    netloc = u.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = u.path
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    kept = []
    for k, v in parse_qsl(u.query, keep_blank_values=False):
        kl = k.lower()
        if kl in _TRACKING_PARAM_NAMES:
            continue
        if any(kl.startswith(p) for p in _TRACKING_PARAM_PREFIXES):
            continue
        kept.append((k, v))
    query = urlencode(kept)
    return urlunparse((u.scheme, netloc, path, "", query, ""))


class SourceScraper:
    """
    Orchestrates scraping all enabled source sites and persists results.
    Supports incremental scraping via content hash comparison (F05).
    """

    def __init__(self, session_id: Optional[int] = None):
        self.scan_session_id = session_id
        self.progress_callbacks: List[Callable] = []
        self._cancelled = False

    def add_progress_callback(self, callback: Callable) -> None:
        self.progress_callbacks.append(callback)

    async def _emit(self, event: str, data: Dict[str, Any]) -> None:
        for cb in self.progress_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(event=event, data=data)
                else:
                    cb(event=event, data=data)
            except Exception as exc:
                logger.debug(f"Progress callback error: {exc}")

    def cancel(self) -> None:
        self._cancelled = True

    async def run_all_sources(self) -> Dict[str, Any]:
        """Run scrape on all enabled source sites."""
        source_sites = config.get("source_sites", default=[])
        enabled_sites = [s for s in source_sites if s.get("enabled", True)]

        overall_stats = {
            "sites_scanned": 0,
            "total_scraped": 0,
            "new_products": 0,
            "updated_products": 0,
            "errors": 0,
        }

        for site in enabled_sites:
            if self._cancelled:
                break
            stats = await self.run_site(site["base_url"], site["name"], site["domain"])
            overall_stats["sites_scanned"] += 1
            overall_stats["total_scraped"] += stats.get("scraped", 0)
            overall_stats["new_products"] += stats.get("new", 0)
            overall_stats["updated_products"] += stats.get("updated", 0)
            overall_stats["errors"] += stats.get("errors", 0)

        return overall_stats

    async def run_site(
        self,
        base_url: str,
        site_name: str,
        domain: str,
    ) -> Dict[str, Any]:
        """Scrape a single source site end-to-end.

        Tries the fast Shopify /products.json path first (all three known
        source sites are Shopify stores at present); falls back to the
        Playwright-driven BaseScraper crawl for non-Shopify sites.
        """
        stats = {"scraped": 0, "new": 0, "updated": 0, "errors": 0, "skipped": 0}

        await self._emit("site_start", {"site": site_name, "url": base_url})
        logger.info(f"Starting scrape of {site_name} ({base_url})")

        # ---- Fast path: Shopify /products.json ----
        if await _is_shopify_store(base_url):
            logger.info("[SCRAPE] %s is a Shopify store — using fast /products.json path", site_name)
            await self._emit("status", {"message": f"Fetching products via Shopify API on {site_name}..."})
            try:
                shopify_products, rate_limited = await scrape_shopify_store(
                    base_url, domain, request_delay_ms=0
                )
            except Exception as exc:
                logger.warning(
                    "[SCRAPE] Shopify fetch failed on %s (%s) — falling back to Playwright crawl",
                    site_name, exc,
                )
                shopify_products = None  # signal fallback
                rate_limited = False

            if shopify_products is not None:
                if rate_limited:
                    logger.warning("[SCRAPE] %s rate-limited during Shopify fetch", site_name)
                logger.info(
                    "[SCRAPE] %s: Shopify returned %d products",
                    site_name, len(shopify_products),
                )
                await self._emit("urls_found", {"site": site_name, "count": len(shopify_products)})

                if self.scan_session_id:
                    with session_scope() as db:
                        sess = db.get(ScanSession, self.scan_session_id)
                        if sess:
                            sess.notes = (sess.notes or "") + (
                                f"\n{site_name}: {len(shopify_products)} products via Shopify API"
                            )

                for idx, product in enumerate(shopify_products):
                    if self._cancelled:
                        await self._emit("cancelled", {"site": site_name})
                        break
                    await self._emit("product_progress", {
                        "site": site_name,
                        "current": idx + 1,
                        "total": len(shopify_products),
                        "url": product.url,
                    })
                    try:
                        if not product.is_valid():
                            stats["skipped"] += 1
                            continue
                        result = self._persist_product(product, domain)
                        stats["scraped"] += 1
                        if result == "new":
                            stats["new"] += 1
                        elif result == "updated":
                            stats["updated"] += 1
                    except Exception as exc:
                        logger.error(f"Error persisting Shopify product {product.url}: {exc}")
                        stats["errors"] += 1

                if self.scan_session_id:
                    with session_scope() as db:
                        sess = db.get(ScanSession, self.scan_session_id)
                        if sess:
                            sess.total_scraped = (sess.total_scraped or 0) + stats["scraped"]
                            sess.new_products = (sess.new_products or 0) + stats["new"]
                            sess.updated_products = (sess.updated_products or 0) + stats["updated"]
                            sess.errors = (sess.errors or 0) + stats["errors"]

                # Admin API: fetch draft / archived if credentials + checkboxes set
                site_cfg = next(
                    (s for s in config.get("source_sites", default=[]) if s.get("domain") == domain),
                    {},
                )
                store_url = site_cfg.get("shopify_store_url", "").strip()
                access_token = site_cfg.get("shopify_access_token", "").strip()
                if store_url and access_token:
                    for admin_status in ("draft", "archived"):
                        key = f"sync_{admin_status}"
                        if site_cfg.get(key):
                            await self._emit("status", {
                                "message": f"Fetching {admin_status} products via Admin API on {site_name}..."
                            })
                            admin_stats = await self._fetch_admin_status_products(
                                store_url, access_token, domain, admin_status
                            )
                            stats[f"{admin_status}_scraped"] = admin_stats["scraped"]
                            stats[f"{admin_status}_new"] = admin_stats["new"]

                archived = self._archive_unseen_for_site(domain)
                stats["archived"] = archived
                await self._emit("site_complete", {"site": site_name, **stats})
                logger.info(f"Completed {site_name} via Shopify API: {stats}")
                return stats

        # ---- Slow path: Playwright crawl + per-page extraction ----
        max_pages = config.get("scraping", "max_pages_per_site", default=200)

        async with BaseScraper(session_id=self.scan_session_id) as scraper:
            # Phase 1: Discover all product URLs
            await self._emit("status", {"message": f"Discovering product URLs on {site_name}..."})

            async def crawl_progress(event, data):
                await self._emit(event, {**data, "site": site_name})

            product_urls = await scraper.discover_product_urls(
                base_url, max_pages=max_pages, progress_callback=crawl_progress
            )

            await self._emit("urls_found", {"site": site_name, "count": len(product_urls)})
            logger.info(f"Found {len(product_urls)} product URLs on {site_name}")

            # Update scan session
            if self.scan_session_id:
                with session_scope() as db:
                    sess = db.get(ScanSession, self.scan_session_id)
                    if sess:
                        sess.notes = (sess.notes or "") + f"\n{site_name}: {len(product_urls)} URLs discovered"

            # Phase 2: Scrape each product page
            for idx, url in enumerate(product_urls):
                if self._cancelled:
                    await self._emit("cancelled", {"site": site_name})
                    break

                await self._emit("product_progress", {
                    "site": site_name,
                    "current": idx + 1,
                    "total": len(product_urls),
                    "url": url,
                })

                try:
                    product = await scraper.extract_product(url, domain)
                    if not product.is_valid():
                        logger.debug(f"Skipping invalid product at {url}")
                        stats["skipped"] += 1
                        continue

                    result = self._persist_product(product, domain)
                    stats["scraped"] += 1
                    if result == "new":
                        stats["new"] += 1
                    elif result == "updated":
                        stats["updated"] += 1

                except Exception as exc:
                    logger.error(f"Error scraping {url}: {exc}")
                    stats["errors"] += 1

        # Update scan session with final stats
        if self.scan_session_id:
            with session_scope() as db:
                sess = db.get(ScanSession, self.scan_session_id)
                if sess:
                    sess.total_scraped = (sess.total_scraped or 0) + stats["scraped"]
                    sess.new_products = (sess.new_products or 0) + stats["new"]
                    sess.updated_products = (sess.updated_products or 0) + stats["updated"]
                    sess.errors = (sess.errors or 0) + stats["errors"]

        # Admin API: fetch draft / archived if credentials + checkboxes set
        site_cfg = next(
            (s for s in config.get("source_sites", default=[]) if s.get("domain") == domain),
            {},
        )
        store_url = site_cfg.get("shopify_store_url", "").strip()
        access_token = site_cfg.get("shopify_access_token", "").strip()
        if store_url and access_token:
            for admin_status in ("draft", "archived"):
                key = f"sync_{admin_status}"
                if site_cfg.get(key):
                    await self._emit("status", {
                        "message": f"Fetching {admin_status} products via Admin API on {site_name}..."
                    })
                    admin_stats = await self._fetch_admin_status_products(
                        store_url, access_token, domain, admin_status
                    )
                    stats[f"{admin_status}_scraped"] = admin_stats["scraped"]
                    stats[f"{admin_status}_new"] = admin_stats["new"]

        archived = self._archive_unseen_for_site(domain)
        stats["archived"] = archived
        await self._emit("site_complete", {"site": site_name, **stats})
        logger.info(f"Completed {site_name}: {stats}")
        return stats

    def _persist_product(self, scraped: ScrapedProduct, source_site: str, source_status: str = "active") -> str:
        """
        Persist a scraped product. Returns "new", "updated", or "skipped".
        Uses content hash for incremental scraping (F05).
        """
        # Canonicalize the URL up front so query-string noise (`?_pos=…&_fid=…&_ss=c`,
        # `utm_*`, `www.` prefix, trailing `/`) doesn't masquerade as a new product.
        canonical = normalize_source_url(scraped.url)

        with session_scope() as db:
            # Check if this canonical URL was already scraped
            existing_source = (
                db.query(ProductSource)
                .filter(
                    ProductSource.source_site == source_site,
                    ProductSource.source_url == canonical,
                )
                .first()
            )

            # Shopify handle fallback: legacy rows may still hold the un-normalized
            # URL form. Match on `/products/<handle>` and migrate to canonical.
            if not existing_source:
                handle_match = re.search(r'/products/([^/?#]+)', canonical)
                if handle_match:
                    handle = handle_match.group(1)
                    candidates = (
                        db.query(ProductSource)
                        .filter(
                            ProductSource.source_site == source_site,
                            ProductSource.source_url.like(f'%/products/{handle}%'),
                        )
                        .all()
                    )
                    for cand in candidates:
                        cand_m = re.search(r'/products/([^/?#]+)', cand.source_url or '')
                        if cand_m and cand_m.group(1) == handle:
                            existing_source = cand
                            cand.source_url = canonical  # migrate to canonical
                            break

            if existing_source:
                # Always stamp scan_session_id so post-scan archive step knows this was seen.
                existing_source.scan_session_id = self.scan_session_id
                existing_source.source_status = source_status
                existing_source.is_active = source_status != "archived"

                # F05: Incremental – skip content update if hash unchanged
                if existing_source.content_hash == scraped.content_hash:
                    return "skipped"

                # Update existing source record
                existing_source.source_title = scraped.title
                existing_source.source_description = scraped.description
                existing_source.source_price = scraped.price
                existing_source.source_price_raw = scraped.price_raw
                existing_source.source_manufacturer = scraped.manufacturer
                existing_source.source_model_number = scraped.model_number
                existing_source.source_sku = scraped.sku
                existing_source.source_category = scraped.category
                existing_source.content_hash = scraped.content_hash
                existing_source.scraped_at = datetime.utcnow()

                # Update master product (F55 versioning handled in dedup engine)
                product = db.get(Product, existing_source.product_id)
                if product:
                    product.updated_at = datetime.utcnow()
                    if scraped.price and (not product.price_canonical or
                            abs((scraped.price - product.price_canonical) / max(product.price_canonical, 0.01)) > 0.01):
                        product.price_canonical = scraped.price

                return "updated"

            else:
                # New product listing — create Product + ProductSource
                product = Product(
                    canonical_title=scraped.title,
                    canonical_description=scraped.description,
                    # Default web-search query = the scraped store title; user-editable.
                    product_search_term=scraped.title,
                    manufacturer=scraped.manufacturer,
                    model_number=scraped.model_number,
                    sku=scraped.sku,
                    price_canonical=scraped.price,
                    price_min=scraped.price,
                    price_max=scraped.price,
                    dimensions_json=json.dumps(scraped.dimensions) if scraped.dimensions else None,
                    specs_json=json.dumps(scraped.specs) if scraped.specs else None,
                    weight=scraped.weight,
                    category=scraped.category,
                    in_stock=scraped.in_stock,
                    content_hash=scraped.content_hash,
                    is_active=True,
                    version=1,
                )
                db.add(product)
                db.flush()  # Get product.id

                source = ProductSource(
                    product_id=product.id,
                    scan_session_id=self.scan_session_id,
                    source_site=source_site,
                    source_url=canonical,
                    source_title=scraped.title,
                    source_description=scraped.description,
                    source_price=scraped.price,
                    source_price_raw=scraped.price_raw,
                    source_manufacturer=scraped.manufacturer,
                    source_model_number=scraped.model_number,
                    source_sku=scraped.sku,
                    source_category=scraped.category,
                    content_hash=scraped.content_hash,
                    is_active=source_status != "archived",
                    source_status=source_status,
                )
                db.add(source)

                # Images
                for i, img_url in enumerate(scraped.images[:8]):
                    db.add(ProductImage(
                        product_id=product.id,
                        source_url=img_url,
                        is_primary=(i == 0),
                        source_site=source_site,
                    ))

                # Options
                for opt in scraped.options[:30]:
                    db.add(ProductOption(
                        product_id=product.id,
                        option_group=opt.get("name"),
                        option_value=opt.get("value"),
                        sku_suffix=opt.get("sku_suffix"),
                        source_site=source_site,
                    ))

                return "new"

    async def _fetch_admin_status_products(
        self, store_url: str, access_token: str, domain: str, status: str
    ) -> Dict[str, int]:
        """Fetch draft or archived products via Shopify Admin API and persist them."""
        from backend.scrapers.base_scraper import ScrapedProduct
        from backend.shopify.client import ShopifyClient
        import re as _re

        stats = {"scraped": 0, "new": 0, "updated": 0, "errors": 0}
        base = store_url.rstrip("/")
        async with ShopifyClient(store_url, access_token) as client:
            async for item in client.iter_products(status=status):
                try:
                    variant = item["variants"][0] if item.get("variants") else {}
                    price_raw = variant.get("price")
                    price = float(price_raw) if price_raw else None
                    images = [img["src"] for img in item.get("images", []) if img.get("src")]
                    sp = ScrapedProduct(
                        url=f"{base}/products/{item['handle']}",
                        title=item.get("title", ""),
                        price=price,
                        price_raw=price_raw,
                        in_stock=variant.get("available", False),
                        sku=variant.get("sku") or None,
                        manufacturer=item.get("vendor") or None,
                        category=(item.get("product_type") or "").strip() or None,
                        description=_re.sub(r"<[^>]+>", " ", item.get("body_html") or "").strip() or None,
                        images=images,
                        source_site=domain,
                    )
                    sp.compute_hash()
                    result = self._persist_product(sp, domain, source_status=status)
                    stats["scraped"] += 1
                    if result == "new":
                        stats["new"] += 1
                    elif result == "updated":
                        stats["updated"] += 1
                except Exception as exc:
                    logger.error("Admin %s fetch error for %s: %s", status, domain, exc)
                    stats["errors"] += 1
        logger.info("Admin %s fetch for %s: %s", status, domain, stats)
        return stats

    def _archive_unseen_for_site(self, domain: str) -> int:
        """Mark source listings not touched by this scan session as archived."""
        if not self.scan_session_id:
            return 0
        with session_scope() as db:
            count = (
                db.query(ProductSource)
                .filter(
                    ProductSource.source_site == domain,
                    ProductSource.source_status != "archived",
                    or_(
                        ProductSource.scan_session_id == None,
                        ProductSource.scan_session_id != self.scan_session_id,
                    ),
                )
                .update(
                    {"source_status": "archived", "is_active": False},
                    synchronize_session=False,
                )
            )
        return count


async def run_source_scan(
    scan_session_id: int,
    site_filter: Optional[str] = None,
    progress_callbacks: Optional[List[Callable]] = None,
) -> Dict[str, Any]:
    """
    Top-level function called by the API to start a source scan.
    site_filter: optional domain to scan only one site.
    """
    scraper = SourceScraper(session_id=scan_session_id)
    if progress_callbacks:
        for cb in progress_callbacks:
            scraper.add_progress_callback(cb)

    with session_scope() as db:
        sess = db.get(ScanSession, scan_session_id)
        if sess:
            sess.status = "running"
            sess.started_at = datetime.utcnow()

    try:
        if site_filter:
            sites = config.get("source_sites", default=[])
            site = next((s for s in sites if s.get("domain") == site_filter), None)
            if not site:
                raise ValueError(f"Site not found: {site_filter}")
            stats = await scraper.run_site(site["base_url"], site["name"], site["domain"])
        else:
            stats = await scraper.run_all_sources()

        with session_scope() as db:
            sess = db.get(ScanSession, scan_session_id)
            if sess:
                sess.status = "completed"
                sess.completed_at = datetime.utcnow()

        return stats

    except Exception as exc:
        logger.error(f"Scan failed: {exc}")
        with session_scope() as db:
            sess = db.get(ScanSession, scan_session_id)
            if sess:
                sess.status = "failed"
                sess.completed_at = datetime.utcnow()
                sess.error_log = str(exc)
        raise
