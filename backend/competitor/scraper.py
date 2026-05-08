"""
Competitor Site Scraper (F14-F16)
Scrapes competitor websites and matches products to the master catalog.
Uses the same multi-strategy extraction as base_scraper.py.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from backend.competitor.matcher import MatchCriteria, match_competitor_product, match_similar_product
from backend.database.db import session_scope
from backend.database.models import (
    Competitor,
    CompetitorProductMatch,
    CompetitorScan,
    PriceHistory,
    Product,
)
from backend.scrapers.base_scraper import BaseScraper, ScrapedProduct

logger = logging.getLogger(__name__)


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
            scraper = BaseScraper(base_url=competitor.base_url or f"https://{competitor.domain}")
            scraped_products: List[ScrapedProduct] = await scraper.scrape_site(
                max_pages=max_pages,
                progress_cb=lambda e, d: emit(e, d),
            )

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
                        competitor_image_url=sp.image_url,
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
            await emit("competitor_scan_error", {
                "competitor": competitor.domain,
                "error": str(exc),
            })
            raise
