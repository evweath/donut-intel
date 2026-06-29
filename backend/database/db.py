"""
Database connection and session management.
Uses SQLite with WAL mode for safe access from Google Drive / shared paths.
"""
import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import config
from backend.database.models import Base

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_engine() -> Engine:
    db_path = config.db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Database path: {db_path}")

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={
            "check_same_thread": False,
            "timeout": 60,
        },
        pool_size=5,
        max_overflow=10,
        echo=config.get("app", "debug", default=False),
    )

    @event.listens_for(engine, "connect")
    def set_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        # WAL mode: safer for network drives (Google Drive), better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA cache_size=-64000")  # 64 MB cache
        cursor.close()

    return engine


_MIGRATIONS = [
    # (table, column, sql_type)  — run ALTER TABLE idempotently on startup
    ("competitor_scraping_profiles", "last_empty_scan_at", "DATETIME"),
    ("competitors", "excluded_from_search", "BOOLEAN DEFAULT 0"),
    ("competitors", "is_manufacturer", "BOOLEAN DEFAULT 0"),
    ("competitors", "is_category_only", "BOOLEAN DEFAULT 0"),
    ("products", "product_search_term", "TEXT"),
    ("beat_price_results", "fuzzy_score", "INTEGER"),
]


def _run_migrations(engine: Engine) -> None:
    """Add columns that may be missing from pre-existing tables (SQLite ALTER TABLE)."""
    with engine.connect() as conn:
        for table, col, col_type in _MIGRATIONS:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
                logger.info("Migration: added %s.%s", table, col)
            except Exception:
                pass  # Column already exists — normal on subsequent startups


def _backfill_product_search_term() -> None:
    """Populate product_search_term for products that don't have one yet.

    Default = the distinct titles scraped from each store, combined (so the
    search query reflects every store's wording), falling back to the canonical
    title when a product has no source listings. Runs once per product: products
    with a non-empty term (including user edits) are left untouched.
    """
    from backend.database.models import Product

    with session_scope() as session:
        products = (
            session.query(Product)
            .filter((Product.product_search_term.is_(None)) | (Product.product_search_term == ""))
            .all()
        )
        if not products:
            return
        filled = 0
        for p in products:
            titles: list = []
            seen: set = set()
            for s in p.sources:
                t = (s.source_title or "").strip()
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    titles.append(t)
            combined = " ".join(titles) if titles else (p.canonical_title or "")
            if combined:
                p.product_search_term = combined
                filled += 1
        logger.info("Backfilled product_search_term for %d products", filled)


def init_db() -> Engine:
    """Initialize DB: create engine, tables, return engine."""
    global _engine, _SessionLocal
    _engine = get_engine()
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(_engine)
    _run_migrations(_engine)
    _backfill_product_search_term()
    logger.info("Database initialized")
    return _engine


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a session and commits/rolls back automatically."""
    if _SessionLocal is None:
        init_db()
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager for use outside of FastAPI dependency injection."""
    if _SessionLocal is None:
        init_db()
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_health_check() -> dict:
    """Return DB health info including WAL mode and path."""
    try:
        path = config.db_path()
        with session_scope() as session:
            wal_mode = session.execute(text("PRAGMA journal_mode")).fetchone()[0]
            size_bytes = path.stat().st_size if path.exists() else 0
        return {
            "status": "ok",
            "path": str(path),
            "wal_mode": wal_mode,
            "size_mb": round(size_bytes / 1024 / 1024, 2),
            "on_network_drive": any(
                marker in str(path)
                for marker in ["GoogleDrive", "OneDrive", "Dropbox", "iCloud", "smb://", "afp://"]
            ),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
