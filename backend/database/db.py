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
            "timeout": 30,
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
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA cache_size=-64000")  # 64 MB cache
        cursor.close()

    return engine


_MIGRATIONS = [
    # (table, column, sql_type)  — run ALTER TABLE idempotently on startup
    ("competitor_scraping_profiles", "last_empty_scan_at", "DATETIME"),
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


def init_db() -> Engine:
    """Initialize DB: create engine, tables, return engine."""
    global _engine, _SessionLocal
    _engine = get_engine()
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(_engine)
    _run_migrations(_engine)
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
