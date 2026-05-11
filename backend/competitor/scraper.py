"""
Competitor Site Scraper (F14-F16)
Scrapes competitor websites and matches products to the master catalog.
Uses the same multi-strategy extraction as base_scraper.py.
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Callable, List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from backend.competitor.matcher import MatchCriteria, match_competitor_product, match_similar_product
from backend.database.db import session_scope
from backend.database.models import (
    Competitor,
    CompetitorProductMatch,
    CompetitorScan,
    CompetitorScrapingProfile,
    PriceHistory,
    Product,
)
from backend.scrapers.base_scraper import BaseScraper, ScrapedProduct

logger = logging.getLogger(__name__)


async def _is_shopify_store(base_url: str) -> bool:
    """Quick check: does /products.json?limit=1 return a products array?"""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(f"{base_url.rstrip('/')}/products.json?limit=1")
            return r.status_code == 200 and "products" in r.json()
    except Exception:
        return False


async def scrape_shopify_store(
    base_url: str, domain: str, request_delay_ms: int = 0
) -> tuple[List[ScrapedProduct], bool]:
    """Paginate through Shopify's /products.json. Returns (products, rate_limited)."""
    products: List[ScrapedProduct] = []
    rate_limited = False
    page = 1
    base = base_url.rstrip("/")
    delay = request_delay_ms / 1000.0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        while True:
            url = f"{base}/products.json?limit=250&page={page}"
            try:
                r = await client.get(url)
                if r.status_code == 429:
                    logger.warning("Shopify %s: rate limited (429) on page %d", domain, page)
                    rate_limited = True
                    break
                r.raise_for_status()
                batch = r.json().get("products", [])
            except httpx.HTTPStatusError as exc:
                logger.warning("Shopify products.json page %d failed: %s", page, exc)
                break
            except Exception as exc:
                logger.warning("Shopify products.json page %d failed: %s", page, exc)
                break
            if not batch:
                break
            for item in batch:
                variant = item["variants"][0] if item.get("variants") else {}
                price_raw = variant.get("price")
                price = float(price_raw) if price_raw else None
                images = [img["src"] for img in item.get("images", []) if img.get("src")]
                sp = ScrapedProduct(
                    url=f"{base}/products/{item['handle']}",
                    title=item.get("title", ""),
                    price=price,
                    in_stock=variant.get("available", True),
                    sku=variant.get("sku") or None,
                    manufacturer=item.get("vendor") or None,
                    description=re.sub(r"<[^>]+>", " ", item.get("body_html") or "").strip() or None,
                    images=images,
                    source_site=domain,
                )
                products.append(sp)
            logger.info("Shopify %s: page %d → %d products so far", domain, page, len(products))
            if len(batch) < 250:
                break
            page += 1
            if delay > 0:
                await asyncio.sleep(delay)
    return products, rate_limited


async def run_competitor_scan(
    competitor_id: int,
    session_name: str,
    criteria_dict: Optional[dict] = None,
    find_similar: bool = False,
    max_pages: int = 100,
    progress_callbacks: Optional[List[Callable]] = None,
) -> dict:
    """
    Full pipeline: scrape a competitor site, match products to master catalog,
    store matches and price history.
    """
    callbacks = progress_callbacks or []

    async def emit(event: str, data: dict):
        for cb in callbacks:
            try:
                await cb(event, data)
            except Exception:
                pass

    criteria = MatchCriteria.from_dict(criteria_dict) if criteria_dict else MatchCriteria()

    with session_scope() as db:
        competitor = db.get(Competitor, competitor_id)
        if not competitor:
            raise ValueError(f"Competitor {competitor_id} not found")

        # Load or create scraping profile
        profile = competitor.scraping_profile
        if profile is None:
            profile = CompetitorScrapingProfile(competitor_id=competitor_id)
            db.add(profile)
            db.flush()

        # Enforce minimum crawl interval
        if profile.min_crawl_interval_hours and profile.last_success_at:
            from datetime import timedelta
            next_allowed = profile.last_success_at + timedelta(hours=profile.min_crawl_interval_hours)
            if datetime.utcnow() < next_allowed:
                logger.info(
                    "Skipping %s — too soon (next allowed: %s)",
                    competitor.domain, next_allowed.isoformat()
                )
                return {
                    "scan_id": None,
                    "competitor": competitor.domain,
                    "products_scraped": 0,
                    "matches_found": 0,
                    "skipped": True,
                    "next_allowed_at": next_allowed.isoformat(),
                }

        # 3-day empty-scan cooldown: skip if last clean (0-product, 0-error) scan was recent
        from datetime import timedelta
        if profile.last_empty_scan_at:
            cooldown_until = profile.last_empty_scan_at + timedelta(days=3)
            if datetime.utcnow() < cooldown_until:
                logger.info(
                    "Skipping %s — 3-day empty-scan cooldown (resets %s)",
                    competitor.domain, cooldown_until.date().isoformat()
                )
                return {
                    "scan_id": None,
                    "competitor": competitor.domain,
                    "products_scraped": 0,
                    "matches_found": 0,
                    "skipped": True,
                    "skipped_reason": "empty_scan_cooldown",
                    "cooldown_until": cooldown_until.isoformat(),
                }

        # Apply profile overrides
        effective_max_pages = profile.max_pages_per_scan or max_pages
        effective_delay_ms = profile.request_delay_ms if profile.request_delay_ms is not None else 0

        comp_scan = CompetitorScan(
            competitor_id=competitor_id,
            session_name=session_name,
            status="running",
        )
        db.add(comp_scan)
        db.flush()
        scan_id = comp_scan.id

        competitor.last_scanned_at = datetime.utcnow()
        if not competitor.first_scanned_at:
            competitor.first_scanned_at = datetime.utcnow()

        # Load master catalog
        master_products = db.query(Product).filter(Product.is_active == True).all()

        await emit("competitor_scan_start", {
            "competitor": competitor.domain,
            "scan_id": scan_id,
            "master_products": len(master_products),
        })

        try:
            base_url = competitor.base_url or f"https://{competitor.domain}"
            rate_limited = False

            if profile.preferred_scraper == "shopify_api" or (
                profile.preferred_scraper == "auto" and await _is_shopify_store(base_url)
            ):
                logger.info("Using Shopify JSON API for %s", competitor.domain)
                profile.platform = "shopify"
                profile.preferred_scraper = "shopify_api"
                scraped_products, rate_limited = await scrape_shopify_store(
                    base_url, competitor.domain, request_delay_ms=effective_delay_ms
                )
            else:
                profile.platform = "playwright"
                if profile.preferred_scraper == "auto":
                    profile.preferred_scraper = "playwright"
                scraper = BaseScraper()
                if effective_delay_ms:
                    scraper.delay = effective_delay_ms / 1000.0
                async with scraper:
                    product_urls = await scraper.discover_product_urls(
                        base_url=base_url,
                        max_pages=effective_max_pages,
                    )
                    await emit("competitor_urls_discovered", {
                        "competitor": competitor.domain,
                        "count": len(product_urls),
                    })
                    scraped_products = []
                    for url in product_urls:
                        try:
                            sp = await scraper.extract_product(url, source_site=competitor.domain)
                            if sp and sp.is_valid():
                                scraped_products.append(sp)
                        except Exception:
                            logger.debug("Failed to extract product from %s", url)
                            continue

            await emit("competitor_products_found", {
                "competitor": competitor.domain,
                "count": len(scraped_products),
            })

            matches_found = 0
            for sp in scraped_products:
                comp_dict = {
                    "title": sp.title,
                    "price": sp.price,
                    "model_number": sp.model_number,
                    "manufacturer": sp.manufacturer,
                    "sku": sp.sku,
                    "description": sp.description,
                    "image_hash": None,
                }

                # Try exact match first
                result = match_competitor_product(comp_dict, master_products, criteria)

                # Fall back to similar match
                if result is None and find_similar:
                    result = match_similar_product(comp_dict, master_products)

                if result is None:
                    continue

                # Check if match already exists
                existing = (
                    db.query(CompetitorProductMatch)
                    .filter(
                        CompetitorProductMatch.master_product_id == result.master_product_id,
                        CompetitorProductMatch.competitor_id == competitor_id,
                        CompetitorProductMatch.competitor_url == sp.url,
                    )
                    .first()
                )

                if existing:
                    # Update price if changed
                    if sp.price and existing.competitor_price != sp.price:
                        old_price = existing.competitor_price
                        existing.competitor_price = sp.price
                        existing.scanned_at = datetime.utcnow()
                        db.add(PriceHistory(match_id=existing.id, price=sp.price, in_stock=sp.in_stock))
                        logger.info(
                            f"Price change on {competitor.domain}: "
                            f"{old_price} -> {sp.price} for {sp.title[:50]}"
                        )
                else:
                    match = CompetitorProductMatch(
                        master_product_id=result.master_product_id,
                        competitor_id=competitor_id,
                        competitor_url=sp.url,
                        competitor_title=sp.title,
                        competitor_price=sp.price,
                        competitor_image_url=sp.images[0] if sp.images else None,
                        match_type="|".join(result.match_types),
                        match_confidence=result.confidence,
                        match_reasons_json=json.dumps(result.reasons),
                        in_stock=sp.in_stock,
                        is_similar=result.is_similar,
                        similarity_reason=result.similarity_reason,
                        scanned_at=datetime.utcnow(),
                    )
                    db.add(match)
                    db.flush()
                    if sp.price:
                        db.add(PriceHistory(match_id=match.id, price=sp.price, in_stock=sp.in_stock))
                    matches_found += 1

            # Update scan record and competitor stats
            comp_scan.status = "completed"
            comp_scan.completed_at = datetime.utcnow()
            comp_scan.products_found = len(scraped_products)
            comp_scan.matches_found = matches_found

            total_matches = (
                db.query(CompetitorProductMatch)
                .filter(
                    CompetitorProductMatch.competitor_id == competitor_id,
                    CompetitorProductMatch.is_active == True,
                )
                .count()
            )
            competitor.total_matching_products = total_matches
            competitor.scan_session_name = session_name

            # Update scraping profile with learned data
            now = datetime.utcnow()
            if rate_limited:
                profile.last_429_at = now
                profile.rate_limit_count = (profile.rate_limit_count or 0) + 1
            profile.last_success_at = now
            profile.consecutive_failures = 0
            if len(scraped_products) > (profile.best_product_count or 0):
                profile.best_product_count = len(scraped_products)
            # Track empty scans: 0 products found with 0 errors → start 3-day cooldown
            if len(scraped_products) == 0 and comp_scan.errors == 0:
                profile.last_empty_scan_at = now
                logger.info(
                    "%s: 0 products found (no errors) — 3-day cooldown started",
                    competitor.domain
                )

            await emit("competitor_scan_complete", {
                "competitor": competitor.domain,
                "scan_id": scan_id,
                "products_found": len(scraped_products),
                "matches_found": matches_found,
            })

            return {
                "scan_id": scan_id,
                "competitor": competitor.domain,
                "products_scraped": len(scraped_products),
                "matches_found": matches_found,
            }

        except Exception as exc:
            logger.exception(f"Competitor scan failed for {competitor.domain}: {exc}")
            comp_scan.status = "failed"
            comp_scan.completed_at = datetime.utcnow()
            comp_scan.errors = 1
            # Update profile failure tracking
            profile.last_error_at = datetime.utcnow()
            profile.last_error_message = str(exc)[:500]
            profile.consecutive_failures = (profile.consecutive_failures or 0) + 1
            await emit("competitor_scan_error", {
                "competitor": competitor.domain,
                "error": str(exc),
            })
            raise
