"""
Source site scraper for Donut Intel Platform (F01–F05).
Scrapes the 3 owned source sites and persists products to the database.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

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
from backend.scrapers.base_scraper import BaseScraper, ScrapedProduct

logger = logging.getLogger(__name__)


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
        """Scrape a single source site end-to-end."""
        stats = {"scraped": 0, "new": 0, "updated": 0, "errors": 0, "skipped": 0}

        await self._emit("site_start", {"site": site_name, "url": base_url})
        logger.info(f"Starting scrape of {site_name} ({base_url})")

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

        await self._emit("site_complete", {"site": site_name, **stats})
        logger.info(f"Completed {site_name}: {stats}")
        return stats

    def _persist_product(self, scraped: ScrapedProduct, source_site: str) -> str:
        """
        Persist a scraped product. Returns "new", "updated", or "skipped".
        Uses content hash for incremental scraping (F05).
        """
        with session_scope() as db:
            # Check if this exact URL was already scraped
            existing_source = (
                db.query(ProductSource)
                .filter(
                    ProductSource.source_site == source_site,
                    ProductSource.source_url == scraped.url,
                )
                .first()
            )

            if existing_source:
                # F05: Incremental – skip if content unchanged
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
                existing_source.scan_session_id = self.scan_session_id

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
                    source_url=scraped.url,
                    source_title=scraped.title,
                    source_description=scraped.description,
                    source_price=scraped.price,
                    source_price_raw=scraped.price_raw,
                    source_manufacturer=scraped.manufacturer,
                    source_model_number=scraped.model_number,
                    source_sku=scraped.sku,
                    source_category=scraped.category,
                    content_hash=scraped.content_hash,
                    is_active=True,
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
