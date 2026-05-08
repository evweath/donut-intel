"""
SQLAlchemy ORM models for Donut Intel Platform.
Schema covers all phases to avoid future migrations.
WAL mode enabled at connection level in db.py for Google Drive compatibility.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Scan Sessions (F04)
# ---------------------------------------------------------------------------
class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    session_type = Column(String(50), nullable=False)  # source | competitor | price_check
    target = Column(String(500))  # URL or "all_sources"
    status = Column(String(50), default="pending")  # pending|running|completed|failed|cancelled
    started_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime)
    total_scraped = Column(Integer, default=0)
    new_products = Column(Integer, default=0)
    updated_products = Column(Integer, default=0)
    duplicates_found = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    error_log = Column(Text)
    notes = Column(Text)

    product_sources = relationship("ProductSource", back_populates="scan_session")


# ---------------------------------------------------------------------------
# Master Product Catalog (F11)
# ---------------------------------------------------------------------------
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_title = Column(String(500), nullable=False)
    canonical_description = Column(Text)
    manufacturer = Column(String(255))
    model_number = Column(String(255))
    sku = Column(String(255))
    price_min = Column(Float)
    price_max = Column(Float)
    price_canonical = Column(Float)
    dimensions_json = Column(Text)  # JSON: {"width": "12in", "height": "8in", ...}
    specs_json = Column(Text)       # JSON: full spec table
    weight = Column(Float)
    country_of_origin = Column(String(100))
    category = Column(String(255))
    subcategory = Column(String(255))
    ai_category = Column(String(255))       # F64 AI-assigned category
    in_stock = Column(Boolean, default=True)
    content_hash = Column(String(64))       # MD5 of key fields for change detection
    version = Column(Integer, default=1)    # F55 product versioning
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    sources = relationship("ProductSource", back_populates="product")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    options = relationship("ProductOption", back_populates="product", cascade="all, delete-orphan")
    tags = relationship("ProductTag", back_populates="product", cascade="all, delete-orphan")
    notes_list = relationship("ProductNote", back_populates="product", cascade="all, delete-orphan")
    versions = relationship("ProductVersion", back_populates="product", cascade="all, delete-orphan")
    as_primary = relationship(
        "DuplicateCandidate",
        foreign_keys="DuplicateCandidate.primary_product_id",
        back_populates="primary_product",
    )
    as_secondary = relationship(
        "DuplicateCandidate",
        foreign_keys="DuplicateCandidate.secondary_product_id",
        back_populates="secondary_product",
    )
    competitor_matches = relationship("CompetitorProductMatch", back_populates="master_product")

    __table_args__ = (
        Index("idx_products_manufacturer", "manufacturer"),
        Index("idx_products_model_number", "model_number"),
        Index("idx_products_sku", "sku"),
        Index("idx_products_category", "category"),
        Index("idx_products_price", "price_canonical"),
    )


# ---------------------------------------------------------------------------
# Product Version History (F55)
# ---------------------------------------------------------------------------
class ProductVersion(Base):
    __tablename__ = "product_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    version = Column(Integer, nullable=False)
    canonical_title = Column(String(500))
    canonical_description = Column(Text)
    manufacturer = Column(String(255))
    model_number = Column(String(255))
    price_canonical = Column(Float)
    changed_fields = Column(Text)  # JSON list of fields that changed
    snapshot_json = Column(Text)   # Full product snapshot as JSON
    created_at = Column(DateTime, default=func.now())

    product = relationship("Product", back_populates="versions")

    __table_args__ = (Index("idx_product_versions_product_id", "product_id"),)


# ---------------------------------------------------------------------------
# Product Sources – per-site listing (F01)
# ---------------------------------------------------------------------------
class ProductSource(Base):
    __tablename__ = "product_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    scan_session_id = Column(Integer, ForeignKey("scan_sessions.id"))
    source_site = Column(String(255), nullable=False)    # e.g. donut-supplies.com
    source_url = Column(String(2000), nullable=False)
    source_title = Column(String(500))
    source_description = Column(Text)
    source_price = Column(Float)
    source_price_raw = Column(String(100))
    source_sku = Column(String(255))
    source_manufacturer = Column(String(255))
    source_model_number = Column(String(255))
    source_category = Column(String(255))
    raw_html_path = Column(String(500))           # F04 optional HTML archive
    content_hash = Column(String(64))             # F05 change detection
    is_active = Column(Boolean, default=True)
    scraped_at = Column(DateTime, default=func.now())

    product = relationship("Product", back_populates="sources")
    scan_session = relationship("ScanSession", back_populates="product_sources")

    __table_args__ = (
        UniqueConstraint("source_site", "source_url", name="uq_source_site_url"),
        Index("idx_product_sources_product_id", "product_id"),
        Index("idx_product_sources_site", "source_site"),
    )


# ---------------------------------------------------------------------------
# Product Options / Variants (F01)
# ---------------------------------------------------------------------------
class ProductOption(Base):
    __tablename__ = "product_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    option_group = Column(String(255))   # e.g. "Size", "Color", "Capacity"
    option_value = Column(String(255))   # e.g. "12L", "Red", "Commercial"
    price_modifier = Column(Float, default=0.0)
    sku_suffix = Column(String(100))
    source_site = Column(String(255))

    product = relationship("Product", back_populates="options")

    __table_args__ = (Index("idx_product_options_product_id", "product_id"),)


# ---------------------------------------------------------------------------
# Product Images (F67 canonical storage)
# ---------------------------------------------------------------------------
class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    source_url = Column(String(2000))
    local_path = Column(String(500))     # F67 downloaded canonical image
    image_hash = Column(String(64))      # F20 perceptual hash (pHash)
    is_primary = Column(Boolean, default=False)
    source_site = Column(String(255))
    alt_text = Column(String(500))
    scraped_at = Column(DateTime, default=func.now())

    product = relationship("Product", back_populates="images")

    __table_args__ = (
        Index("idx_product_images_product_id", "product_id"),
        Index("idx_product_images_hash", "image_hash"),
    )


# ---------------------------------------------------------------------------
# Duplicate Candidates (F06–F10)
# ---------------------------------------------------------------------------
class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    primary_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    secondary_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    confidence_score = Column(Float, nullable=False)    # 0–100
    match_reasons_json = Column(Text)                   # JSON: breakdown of scores per factor
    status = Column(String(50), default="pending")      # pending|merged|rejected|review
    resolved_at = Column(DateTime)
    resolved_by = Column(String(100))                   # "auto" or username
    resolution_notes = Column(Text)
    created_at = Column(DateTime, default=func.now())

    primary_product = relationship(
        "Product", foreign_keys=[primary_product_id], back_populates="as_primary"
    )
    secondary_product = relationship(
        "Product", foreign_keys=[secondary_product_id], back_populates="as_secondary"
    )

    __table_args__ = (
        UniqueConstraint("primary_product_id", "secondary_product_id", name="uq_dup_pair"),
        Index("idx_dup_candidates_status", "status"),
        Index("idx_dup_candidates_score", "confidence_score"),
    )


# ---------------------------------------------------------------------------
# Competitor Sites (F14)
# ---------------------------------------------------------------------------
class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(255), nullable=False, unique=True)
    name = Column(String(255))
    base_url = Column(String(1000))
    first_scanned_at = Column(DateTime)
    last_scanned_at = Column(DateTime)
    total_matching_products = Column(Integer, default=0)
    scan_session_name = Column(String(255))   # e.g. "Monday Top 20"
    is_active = Column(Boolean, default=True)
    notes = Column(Text)
    added_at = Column(DateTime, default=func.now())

    scans = relationship("CompetitorScan", back_populates="competitor")
    matches = relationship("CompetitorProductMatch", back_populates="competitor")


# ---------------------------------------------------------------------------
# Competitor Scan Sessions (F15–F16)
# ---------------------------------------------------------------------------
class CompetitorScan(Base):
    __tablename__ = "competitor_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=False)
    session_name = Column(String(255))
    status = Column(String(50), default="pending")
    started_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime)
    products_found = Column(Integer, default=0)
    matches_found = Column(Integer, default=0)
    errors = Column(Integer, default=0)

    competitor = relationship("Competitor", back_populates="scans")


# ---------------------------------------------------------------------------
# Competitor Product Matches (F17–F21)
# ---------------------------------------------------------------------------
class CompetitorProductMatch(Base):
    __tablename__ = "competitor_product_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    master_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=False)
    competitor_url = Column(String(2000))
    competitor_title = Column(String(500))
    competitor_price = Column(Float)
    competitor_image_url = Column(String(2000))
    local_image_path = Column(String(500))
    match_type = Column(String(100))       # model|manufacturer|title_exact|title_fuzzy|image|price
    match_confidence = Column(Float)       # 0–100
    match_reasons_json = Column(Text)      # JSON breakdown
    in_stock = Column(Boolean)
    is_similar = Column(Boolean, default=False)   # F27 similar-but-not-identical
    similarity_reason = Column(Text)              # F29 why it's similar
    scanned_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)

    master_product = relationship("Product", back_populates="competitor_matches")
    competitor = relationship("Competitor", back_populates="matches")
    price_history = relationship("PriceHistory", back_populates="match")

    __table_args__ = (
        Index("idx_comp_matches_master", "master_product_id"),
        Index("idx_comp_matches_competitor", "competitor_id"),
        Index("idx_comp_matches_price", "competitor_price"),
    )


# ---------------------------------------------------------------------------
# Price History (F24)
# ---------------------------------------------------------------------------
class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("competitor_product_matches.id"), nullable=False)
    price = Column(Float, nullable=False)
    in_stock = Column(Boolean)
    recorded_at = Column(DateTime, default=func.now())

    match = relationship("CompetitorProductMatch", back_populates="price_history")

    __table_args__ = (Index("idx_price_history_match", "match_id"),)


# ---------------------------------------------------------------------------
# Scheduled Jobs (F43–F44)
# ---------------------------------------------------------------------------
class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    job_type = Column(String(100))        # source_scan|competitor_scan|price_check|export
    target = Column(String(500))          # URL, "all_sources", competitor_id list, etc.
    schedule_type = Column(String(50))    # one_time|daily|weekly|monthly|cron
    schedule_value = Column(String(255))  # cron expression or ISO datetime
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime)
    next_run_at = Column(DateTime)
    last_status = Column(String(50))
    run_count = Column(Integer, default=0)
    config_json = Column(Text)            # JSON: extra job config
    created_at = Column(DateTime, default=func.now())


# ---------------------------------------------------------------------------
# Export History (F42)
# ---------------------------------------------------------------------------
class ExportRecord(Base):
    __tablename__ = "export_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    export_type = Column(String(50))    # xlsx|csv|txt|pdf|html
    filename = Column(String(500))
    file_path = Column(String(1000))
    scope = Column(String(255))         # "all_products", "competitor:domain", etc.
    row_count = Column(Integer)
    triggered_by = Column(String(100))  # "user"|"scheduler"
    created_at = Column(DateTime, default=func.now())


# ---------------------------------------------------------------------------
# Tags & Notes (F71)
# ---------------------------------------------------------------------------
class ProductTag(Base):
    __tablename__ = "product_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    tag = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=func.now())

    product = relationship("Product", back_populates="tags")

    __table_args__ = (
        UniqueConstraint("product_id", "tag", name="uq_product_tag"),
        Index("idx_product_tags_tag", "tag"),
    )


class ProductNote(Base):
    __tablename__ = "product_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    note_text = Column(Text, nullable=False)
    created_by = Column(String(100), default="user")
    created_at = Column(DateTime, default=func.now())

    product = relationship("Product", back_populates="notes_list")


# ---------------------------------------------------------------------------
# App Settings (F56 – persisted UI settings)
# ---------------------------------------------------------------------------
class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(255), nullable=False, unique=True)
    value = Column(Text)
    description = Column(String(500))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
