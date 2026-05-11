"""
Deduplication engine for Donut Intel Platform (F06–F11).
Detects duplicate products across the 3 source websites.
Duplicates = same product listed on 2+ different source sites (not within one site).
"""
import json
import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.config import config
from backend.database.models import (
    DuplicateCandidate,
    Product,
    ProductSource,
    ProductVersion,
)
from backend.dedup.matchers import compute_confidence

logger = logging.getLogger(__name__)


class DeduplicationEngine:
    def __init__(self):
        self.auto_merge_threshold: float = config.get(
            "deduplication", "auto_merge_threshold", default=85
        )
        self.review_threshold: float = config.get(
            "deduplication", "manual_review_threshold", default=60
        )
        self.price_weight: int = config.get("deduplication", "price_weight", default=40)
        self.model_weight: int = config.get("deduplication", "model_number_weight", default=35)
        self.manufacturer_weight: int = config.get("deduplication", "manufacturer_weight", default=15)
        self.title_weight: int = config.get("deduplication", "title_weight", default=20)
        self.desc_weight: int = config.get("deduplication", "description_weight", default=10)
        self.price_tolerance: float = config.get(
            "deduplication", "price_tolerance_percent", default=2.0
        )

    def run(
        self,
        session: Session,
        product_ids: Optional[List[int]] = None,
        domain_filters: Optional[List[str]] = None,
    ) -> dict:
        """
        Run deduplication across all products (or a subset).
        Only compares products from DIFFERENT source sites.
        Returns summary stats.
        """
        logger.info("Starting deduplication run")
        stats = {
            "comparisons": 0,
            "auto_merged": 0,
            "flagged_for_review": 0,
            "skipped_existing": 0,
        }

        # Load all active products with their source site info
        query = session.query(Product).filter(Product.is_active == True)
        if product_ids:
            query = query.filter(Product.id.in_(product_ids))
        if domain_filters:
            query = query.filter(
                Product.sources.any(
                    ProductSource.source_site.in_(domain_filters) & (ProductSource.is_active == True)
                )
            )
        products = query.all()

        logger.info(f"Comparing {len(products)} products for duplicates")

        # Build a list: (product, set_of_source_sites)
        product_data = []
        for p in products:
            sites = {s.source_site for s in p.sources if s.is_active}
            product_data.append((p, sites))

        # O(n²) comparison — acceptable for <10k products; blocking can be added later
        already_checked = set()
        for i, (prod_a, sites_a) in enumerate(product_data):
            for j, (prod_b, sites_b) in enumerate(product_data):
                if i >= j:
                    continue
                # Only compare across DIFFERENT source sites
                if sites_a == sites_b and len(sites_a) == 1:
                    continue
                # Don't compare products that already have a resolved duplicate record
                pair_key = (min(prod_a.id, prod_b.id), max(prod_a.id, prod_b.id))
                if pair_key in already_checked:
                    stats["skipped_existing"] += 1
                    continue
                already_checked.add(pair_key)

                # Check if a duplicate record already exists (any status)
                existing = (
                    session.query(DuplicateCandidate)
                    .filter(
                        DuplicateCandidate.primary_product_id == pair_key[0],
                        DuplicateCandidate.secondary_product_id == pair_key[1],
                    )
                    .first()
                )
                if existing and existing.status in ("merged", "rejected"):
                    stats["skipped_existing"] += 1
                    continue

                stats["comparisons"] += 1
                confidence, factor_scores = compute_confidence(
                    price_a=prod_a.price_canonical,
                    price_b=prod_b.price_canonical,
                    model_a=prod_a.model_number,
                    model_b=prod_b.model_number,
                    manufacturer_a=prod_a.manufacturer,
                    manufacturer_b=prod_b.manufacturer,
                    title_a=prod_a.canonical_title,
                    title_b=prod_b.canonical_title,
                    desc_a=prod_a.canonical_description,
                    desc_b=prod_b.canonical_description,
                    sku_a=prod_a.sku,
                    sku_b=prod_b.sku,
                    price_weight=self.price_weight,
                    model_weight=self.model_weight,
                    manufacturer_weight=self.manufacturer_weight,
                    title_weight=self.title_weight,
                    description_weight=self.desc_weight,
                    price_tolerance_pct=self.price_tolerance,
                )

                if confidence < self.review_threshold:
                    continue

                if existing:
                    # Update score if re-running
                    existing.confidence_score = confidence
                    existing.match_reasons_json = json.dumps(factor_scores)
                    if existing.status == "pending":
                        if confidence >= self.auto_merge_threshold:
                            self._merge_products(session, prod_a, prod_b, existing, auto=True)
                            stats["auto_merged"] += 1
                        else:
                            stats["flagged_for_review"] += 1
                else:
                    candidate = DuplicateCandidate(
                        primary_product_id=pair_key[0],
                        secondary_product_id=pair_key[1],
                        confidence_score=confidence,
                        match_reasons_json=json.dumps(factor_scores),
                        status="pending",
                    )
                    session.add(candidate)
                    session.flush()

                    if confidence >= self.auto_merge_threshold:
                        self._merge_products(session, prod_a, prod_b, candidate, auto=True)
                        stats["auto_merged"] += 1
                    else:
                        stats["flagged_for_review"] += 1

        session.commit()
        logger.info(f"Deduplication complete: {stats}")
        return stats

    def _merge_products(
        self,
        session: Session,
        primary: Product,
        secondary: Product,
        candidate: DuplicateCandidate,
        auto: bool = True,
        notes: str = "",
        resolved_by: str = "auto",
    ) -> None:
        """
        Merge secondary into primary:
        - Move all sources from secondary → primary
        - Merge images, options, tags, notes
        - Consolidate price (min/max/canonical)
        - Archive version of primary before changes (F55)
        - Deactivate secondary product
        """
        # Archive current state of primary (F55)
        self._archive_version(session, primary, changed_fields=["merge"])

        # Re-attach secondary sources to primary
        for src in secondary.sources:
            # Check if primary already has a source from the same site+URL
            exists = any(
                s.source_site == src.source_site and s.source_url == src.source_url
                for s in primary.sources
            )
            if not exists:
                src.product_id = primary.id

        # Merge images
        existing_image_urls = {img.source_url for img in primary.images}
        for img in secondary.images:
            if img.source_url not in existing_image_urls:
                img.product_id = primary.id

        # Merge options
        existing_options = {
            (o.option_group, o.option_value) for o in primary.options
        }
        for opt in secondary.options:
            if (opt.option_group, opt.option_value) not in existing_options:
                opt.product_id = primary.id

        # Update price range
        all_prices = [
            p for p in [
                primary.price_canonical,
                secondary.price_canonical,
                primary.price_min,
                secondary.price_min,
                primary.price_max,
                secondary.price_max,
            ]
            if p and p > 0
        ]
        if all_prices:
            primary.price_min = min(all_prices)
            primary.price_max = max(all_prices)
            # Canonical = most commonly occurring price (first pass: use average)
            primary.price_canonical = sum(all_prices) / len(all_prices)

        # Fill in missing fields from secondary
        if not primary.manufacturer and secondary.manufacturer:
            primary.manufacturer = secondary.manufacturer
        if not primary.model_number and secondary.model_number:
            primary.model_number = secondary.model_number
        if not primary.sku and secondary.sku:
            primary.sku = secondary.sku
        if not primary.canonical_description and secondary.canonical_description:
            primary.canonical_description = secondary.canonical_description

        primary.updated_at = datetime.utcnow()

        # Deactivate secondary
        secondary.is_active = False

        # Update candidate record
        candidate.status = "merged"
        candidate.resolved_at = datetime.utcnow()
        candidate.resolved_by = resolved_by
        candidate.resolution_notes = notes or ("Auto-merged" if auto else "Manual merge")

        session.flush()

    def reject_duplicate(
        self,
        session: Session,
        candidate_id: int,
        notes: str = "",
        resolved_by: str = "user",
    ) -> bool:
        candidate = session.get(DuplicateCandidate, candidate_id)
        if not candidate:
            return False
        candidate.status = "rejected"
        candidate.resolved_at = datetime.utcnow()
        candidate.resolved_by = resolved_by
        candidate.resolution_notes = notes
        session.commit()
        return True

    def manual_merge(
        self,
        session: Session,
        candidate_id: int,
        notes: str = "",
        resolved_by: str = "user",
    ) -> bool:
        candidate = session.get(DuplicateCandidate, candidate_id)
        if not candidate:
            return False
        if candidate.status == "merged":
            return True
        primary = session.get(Product, candidate.primary_product_id)
        secondary = session.get(Product, candidate.secondary_product_id)
        if not primary or not secondary:
            return False
        self._merge_products(session, primary, secondary, candidate, auto=False, notes=notes, resolved_by=resolved_by)
        session.commit()
        return True

    def _archive_version(self, session: Session, product: Product, changed_fields: list) -> None:
        """Save a version snapshot of product before modification (F55)."""
        import json as _json
        snapshot = {
            "canonical_title": product.canonical_title,
            "canonical_description": product.canonical_description,
            "manufacturer": product.manufacturer,
            "model_number": product.model_number,
            "sku": product.sku,
            "price_canonical": product.price_canonical,
            "price_min": product.price_min,
            "price_max": product.price_max,
            "category": product.category,
        }
        version = ProductVersion(
            product_id=product.id,
            version=product.version,
            canonical_title=product.canonical_title,
            canonical_description=product.canonical_description,
            manufacturer=product.manufacturer,
            model_number=product.model_number,
            price_canonical=product.price_canonical,
            changed_fields=_json.dumps(changed_fields),
            snapshot_json=_json.dumps(snapshot),
        )
        session.add(version)
        product.version = (product.version or 1) + 1
