"""Persistent snapshots of live Shopify catalog and navigation scans."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MAX_AGE_DAYS = 5
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "scan_cache"


def _safe_name(domain: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", (domain or "").strip().lower())


def _path(domain: str) -> Path:
    return _CACHE_DIR / f"{_safe_name(domain)}.json"


def save_scan(domain: str, snapshot: Dict[str, Any]) -> None:
    if not domain:
        return
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "domain": domain,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": snapshot,
    }
    dest = _path(domain)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        with tmp.open("w") as f:
            json.dump(payload, f)
        tmp.replace(dest)
    except Exception:
        logger.exception("scan_cache.save_scan: failed to persist %s", domain)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _load_payload(domain: str) -> Optional[Dict[str, Any]]:
    path = _path(domain)
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        logger.exception("scan_cache: could not read cache for %s", domain)
        return None


def _age_seconds(scanned_at: str) -> Optional[float]:
    try:
        ts = datetime.fromisoformat(scanned_at)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _fresh(payload: Dict[str, Any], max_age_days: float) -> Optional[float]:
    age = _age_seconds(payload.get("scanned_at", ""))
    if age is None or age > max_age_days * 86400:
        return None
    return age


def scan_info(domain: str, max_age_days: float = MAX_AGE_DAYS) -> Optional[Dict[str, Any]]:
    payload = _load_payload(domain)
    if not payload:
        return None
    age = _fresh(payload, max_age_days)
    if age is None:
        return None
    snap = payload.get("snapshot") or {}
    return {
        "domain": domain,
        "scanned_at": payload.get("scanned_at"),
        "age_seconds": age,
        "age_days": round(age / 86400, 2),
        "product_count": len(snap.get("products") or {}),
        "menu_count": len(snap.get("menus") or []),
        "menu_error": snap.get("menu_error"),
        "shop_name": (snap.get("shop") or {}).get("name", ""),
        "max_age_days": max_age_days,
    }


def load_snapshot(domain: str, max_age_days: float = MAX_AGE_DAYS) -> Optional[Dict[str, Any]]:
    payload = _load_payload(domain)
    if not payload or _fresh(payload, max_age_days) is None:
        return None
    return payload.get("snapshot")


def all_info(max_age_days: float = MAX_AGE_DAYS) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not _CACHE_DIR.exists():
        return out
    for path in _CACHE_DIR.glob("*.json"):
        try:
            with path.open() as f:
                domain = json.load(f).get("domain")
        except Exception:
            continue
        if not domain:
            continue
        info = scan_info(domain, max_age_days)
        if info:
            out[domain] = info
    return out
