"""
FastAPI route handlers for Donut Intel Platform — Phase 2 complete.
Covers: scraping, dedup, products, competitors, price comparison,
        scheduler, export, reports, AI categorization, webhooks, bulk import.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from backend.config import config
from backend.database.db import get_db_session, db_health_check, session_scope
from backend.database.models import (
    AppSetting,
    Competitor,
    CompetitorProductMatch,
    CompetitorScan,
    DuplicateCandidate,
    ExportRecord,
    PriceHistory,
    Product,
    ProductNote,
    ProductSource,
    ProductTag,
    ScheduledJob,
    ScanSession,
)
from backend.dedup.engine import DeduplicationEngine
from backend.scrapers.source_scraper import run_source_scan

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
_active_scans: Dict[int, Any] = {}

from backend.tasks.manager import task_manager as _task_manager
_task_manager.set_broadcast(manager.broadcast)


@router.websocket("/ws/scan-progress")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------

@router.get("/api/stats")
def get_stats(db: Session = Depends(get_db_session)):
    total_products = db.query(func.count(Product.id)).filter(Product.is_active == True).scalar() or 0
    total_sources = db.query(func.count(ProductSource.id)).filter(ProductSource.is_active == True).scalar() or 0
    pending_dupes = (
        db.query(func.count(DuplicateCandidate.id))
        .filter(DuplicateCandidate.status == "pending").scalar() or 0
    )
    total_competitors = db.query(func.count(Competitor.id)).filter(Competitor.is_active == True).scalar() or 0
    total_comp_matches = (
        db.query(func.count(CompetitorProductMatch.id))
        .filter(CompetitorProductMatch.is_active == True).scalar() or 0
    )
    last_scan = (
        db.query(ScanSession)
        .filter(ScanSession.session_type == "source")
        .order_by(ScanSession.started_at.desc()).first()
    )
    site_counts = (
        db.query(ProductSource.source_site, func.count(ProductSource.id))
        .filter(ProductSource.is_active == True)
        .group_by(ProductSource.source_site).all()
    )
    categories = (
        db.query(Product.category, func.count(Product.id))
        .filter(Product.is_active == True, Product.category != None)
        .group_by(Product.category)
        .order_by(func.count(Product.id).desc()).limit(10).all()
    )
    return {
        "total_products": total_products,
        "total_sources": total_sources,
        "pending_duplicates": pending_dupes,
        "total_competitors": total_competitors,
        "total_competitor_matches": total_comp_matches,
        "last_scan": {
            "id": last_scan.id,
            "status": last_scan.status,
            "started_at": last_scan.started_at.isoformat() if last_scan else None,
            "completed_at": last_scan.completed_at.isoformat() if last_scan and last_scan.completed_at else None,
            "new_products": last_scan.new_products,
        } if last_scan else None,
        "products_by_site": {site: count for site, count in site_counts},
        "categories": [{"category": cat or "Uncategorized", "count": cnt} for cat, cnt in categories],
        "db": db_health_check(),
    }


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@router.get("/api/products")
def list_products(
    search: Optional[str] = None,
    manufacturer: Optional[str] = None,
    category: Optional[str] = None,
    source_site: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db_session),
):
    per_page = min(per_page, 200)
    query = db.query(Product).filter(Product.is_active == True)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Product.canonical_title.ilike(like),
            Product.manufacturer.ilike(like),
            Product.model_number.ilike(like),
            Product.sku.ilike(like),
        ))
    if manufacturer:
        query = query.filter(Product.manufacturer.ilike(f"%{manufacturer}%"))
    if category:
        query = query.filter(Product.category.ilike(f"%{category}%"))
    if source_site:
        query = query.join(Product.sources).filter(ProductSource.source_site == source_site)
    if min_price is not None:
        query = query.filter(Product.price_canonical >= min_price)
    if max_price is not None:
        query = query.filter(Product.price_canonical <= max_price)
    total = query.count()
    products = query.order_by(Product.canonical_title).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "products": [_serialize_product(p) for p in products],
    }


@router.get("/api/products/filters/options")
def get_filter_options(db: Session = Depends(get_db_session)):
    manufacturers = (
        db.query(Product.manufacturer)
        .filter(Product.is_active == True, Product.manufacturer != None)
        .distinct().order_by(Product.manufacturer).all()
    )
    categories = (
        db.query(Product.category)
        .filter(Product.is_active == True, Product.category != None)
        .distinct().order_by(Product.category).all()
    )
    sites = db.query(ProductSource.source_site).filter(ProductSource.is_active == True).distinct().all()
    return {
        "manufacturers": [m[0] for m in manufacturers if m[0]],
        "categories": [c[0] for c in categories if c[0]],
        "source_sites": [s[0] for s in sites if s[0]],
    }


@router.get("/api/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db_session)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize_product(product, full=True)


@router.get("/api/products/{product_id}/price-comparison")
def product_price_comparison(product_id: int, db: Session = Depends(get_db_session)):
    """F22: Ranked price comparison for one product."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    prices = []
    for source in product.sources:
        if source.is_active and source.source_price:
            prices.append({
                "site": source.source_site,
                "price": source.source_price,
                "url": source.source_url,
                "type": "source",
                "scanned_at": source.scraped_at.isoformat() if source.scraped_at else None,
            })

    matches = (
        db.query(CompetitorProductMatch)
        .filter(
            CompetitorProductMatch.master_product_id == product_id,
            CompetitorProductMatch.is_active == True,
            CompetitorProductMatch.competitor_price > 0,
        ).all()
    )
    for m in matches:
        comp = db.get(Competitor, m.competitor_id)
        prices.append({
            "site": comp.domain if comp else "?",
            "price": m.competitor_price,
            "url": m.competitor_url,
            "type": "competitor",
            "in_stock": m.in_stock,
            "scanned_at": m.scanned_at.isoformat() if m.scanned_at else None,
            "match_type": m.match_type,
        })

    prices.sort(key=lambda x: x["price"])

    # F23: flag outliers > 15% from median
    if prices:
        sorted_prices = sorted(p["price"] for p in prices)
        median = sorted_prices[len(sorted_prices) // 2]
        threshold = config.get("price_alerts", "outlier_threshold_pct", default=15)
        for p in prices:
            dev = abs(p["price"] - median) / median * 100
            p["is_outlier"] = dev > threshold
            p["deviation_pct"] = round(dev, 1)

    return {
        "product_id": product_id,
        "product_title": product.canonical_title,
        "our_price": product.price_canonical,
        "prices": prices,
        "cheapest": prices[0] if prices else None,
        "most_expensive": prices[-1] if prices else None,
    }


@router.get("/api/products/{product_id}/price-history")
def product_price_history(product_id: int, db: Session = Depends(get_db_session)):
    """F24: Price history over time for a product across all competitors."""
    matches = (
        db.query(CompetitorProductMatch)
        .filter(
            CompetitorProductMatch.master_product_id == product_id,
            CompetitorProductMatch.is_active == True,
        ).all()
    )
    result = []
    for m in matches:
        comp = db.get(Competitor, m.competitor_id)
        history = (
            db.query(PriceHistory)
            .filter(PriceHistory.match_id == m.id)
            .order_by(PriceHistory.recorded_at)
            .all()
        )
        result.append({
            "competitor": comp.domain if comp else "?",
            "current_price": m.competitor_price,
            "history": [
                {"price": ph.price, "in_stock": ph.in_stock, "recorded_at": ph.recorded_at.isoformat()}
                for ph in history
            ],
        })
    return {"product_id": product_id, "competitors": result}


def _serialize_product(p: Product, full: bool = False) -> dict:
    sources = [
        {"id": s.id, "site": s.source_site, "url": s.source_url, "title": s.source_title,
         "price": s.source_price, "scraped_at": s.scraped_at.isoformat() if s.scraped_at else None}
        for s in p.sources if s.is_active
    ]
    images = [
        {"url": img.source_url, "local_path": img.local_path, "is_primary": img.is_primary}
        for img in p.images
    ]
    comp_count = len([m for m in p.competitor_matches if m.is_active])
    result = {
        "id": p.id, "title": p.canonical_title, "manufacturer": p.manufacturer,
        "model_number": p.model_number, "sku": p.sku, "price": p.price_canonical,
        "price_min": p.price_min, "price_max": p.price_max, "category": p.category,
        "subcategory": p.subcategory, "ai_category": p.ai_category,
        "in_stock": p.in_stock, "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "sources": sources, "competitor_matches": comp_count,
        "primary_image": next((img["url"] for img in images if img["is_primary"]), images[0]["url"] if images else None),
    }
    if full:
        result.update({
            "description": p.canonical_description,
            "dimensions": json.loads(p.dimensions_json) if p.dimensions_json else None,
            "specs": json.loads(p.specs_json) if p.specs_json else None,
            "weight": p.weight, "country_of_origin": p.country_of_origin,
            "images": images,
            "options": [{"group": o.option_group, "value": o.option_value, "price_modifier": o.price_modifier} for o in p.options],
            "tags": [t.tag for t in p.tags],
            "notes": [{"text": n.note_text, "created_at": n.created_at.isoformat(), "by": n.created_by} for n in p.notes_list],
            "version": p.version,
        })
    return result


# ---------------------------------------------------------------------------
# Source Scan Control (F01-F05)
# ---------------------------------------------------------------------------

class StartScanRequest(BaseModel):
    site_filter: Optional[str] = None
    name: Optional[str] = None


@router.post("/api/scan/sources")
async def start_source_scan(req: StartScanRequest, db: Session = Depends(get_db_session)):
    scan_session = ScanSession(
        name=req.name or f"Source Scan {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        session_type="source", target=req.site_filter or "all_sources", status="pending",
    )
    db.add(scan_session)
    db.flush()
    session_id = scan_session.id
    db.commit()

    async def do_scan():
        from backend.app import capture_error
        async def ws_progress(event: str, data: dict):
            await manager.broadcast({"event": event, "session_id": session_id, **data})
        try:
            await run_source_scan(scan_session_id=session_id, site_filter=req.site_filter, progress_callbacks=[ws_progress])
            await manager.broadcast({"event": "scan_complete", "session_id": session_id})
        except Exception as exc:
            capture_error(exc, context=f"source_scan session={session_id}")
            await manager.broadcast({"event": "scan_error", "session_id": session_id, "error": str(exc)})
        finally:
            _active_scans.pop(session_id, None)

    task = asyncio.create_task(do_scan())
    _active_scans[session_id] = task
    return {"scan_session_id": session_id, "status": "started"}


@router.delete("/api/scan/{session_id}/cancel")
def cancel_scan(session_id: int, db: Session = Depends(get_db_session)):
    task = _active_scans.get(session_id)
    if task:
        task.cancel()
        _active_scans.pop(session_id, None)
    sess = db.get(ScanSession, session_id)
    if sess and sess.status == "running":
        sess.status = "cancelled"
        sess.completed_at = datetime.utcnow()
    return {"status": "cancellation_requested"}


@router.get("/api/scan/sessions")
def list_scan_sessions(page: int = 1, per_page: int = 20, db: Session = Depends(get_db_session)):
    total = db.query(func.count(ScanSession.id)).scalar() or 0
    sessions = (
        db.query(ScanSession).order_by(ScanSession.started_at.desc())
        .offset((page - 1) * per_page).limit(per_page).all()
    )
    return {
        "total": total,
        "sessions": [
            {"id": s.id, "name": s.name, "type": s.session_type, "target": s.target,
             "status": s.status,
             "started_at": s.started_at.isoformat() if s.started_at else None,
             "completed_at": s.completed_at.isoformat() if s.completed_at else None,
             "total_scraped": s.total_scraped, "new_products": s.new_products,
             "updated_products": s.updated_products, "errors": s.errors}
            for s in sessions
        ],
    }


@router.get("/api/scan/{session_id}/status")
def get_scan_status(session_id: int, db: Session = Depends(get_db_session)):
    sess = db.get(ScanSession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return {
        "id": sess.id, "status": sess.status, "total_scraped": sess.total_scraped,
        "new_products": sess.new_products, "updated_products": sess.updated_products,
        "errors": sess.errors, "is_active": sess.id in _active_scans,
    }


# ---------------------------------------------------------------------------
# Deduplication (F06-F11)
# ---------------------------------------------------------------------------

class DeduplicateRequest(BaseModel):
    product_ids: Optional[List[int]] = None


@router.post("/api/dedup/run")
async def run_deduplication(req: DeduplicateRequest):
    async def do_dedup():
        with session_scope() as s:
            engine = DeduplicationEngine()
            stats = engine.run(s, req.product_ids)
            await manager.broadcast({"event": "dedup_complete", "stats": stats})
    asyncio.create_task(do_dedup())
    return {"status": "dedup_started"}


@router.get("/api/dedup/candidates")
def list_duplicate_candidates(status: str = "pending", page: int = 1, per_page: int = 20, db: Session = Depends(get_db_session)):
    query = db.query(DuplicateCandidate)
    if status != "all":
        query = query.filter(DuplicateCandidate.status == status)
    total = query.count()
    candidates = query.order_by(DuplicateCandidate.confidence_score.desc()).offset((page - 1) * per_page).limit(per_page).all()
    results = []
    for c in candidates:
        primary = db.get(Product, c.primary_product_id)
        secondary = db.get(Product, c.secondary_product_id)
        if not primary or not secondary:
            continue
        results.append({
            "id": c.id, "confidence_score": c.confidence_score, "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "match_reasons": json.loads(c.match_reasons_json) if c.match_reasons_json else {},
            "primary": {"id": primary.id, "title": primary.canonical_title, "price": primary.price_canonical,
                        "manufacturer": primary.manufacturer, "model_number": primary.model_number,
                        "sku": primary.sku,
                        "sources": [s.source_site for s in primary.sources if s.is_active],
                        "image": next((img.source_url for img in primary.images if img.is_primary), None)},
            "secondary": {"id": secondary.id, "title": secondary.canonical_title, "price": secondary.price_canonical,
                          "manufacturer": secondary.manufacturer, "model_number": secondary.model_number,
                          "sku": secondary.sku,
                          "sources": [s.source_site for s in secondary.sources if s.is_active],
                          "image": next((img.source_url for img in secondary.images if img.is_primary), None)},
        })
    return {"total": total, "candidates": results}


class ResolveRequest(BaseModel):
    action: str
    notes: Optional[str] = None


@router.post("/api/dedup/candidates/{candidate_id}/resolve")
def resolve_duplicate(candidate_id: int, req: ResolveRequest, db: Session = Depends(get_db_session)):
    engine = DeduplicationEngine()
    if req.action == "merge":
        ok = engine.manual_merge(db, candidate_id, notes=req.notes or "", resolved_by="user")
    elif req.action == "reject":
        ok = engine.reject_duplicate(db, candidate_id, notes=req.notes or "", resolved_by="user")
    else:
        raise HTTPException(status_code=400, detail="action must be 'merge' or 'reject'")
    if not ok:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return {"status": "resolved", "action": req.action}


# ---------------------------------------------------------------------------
# Competitors (F12-F21)
# ---------------------------------------------------------------------------

class DiscoverCompetitorsRequest(BaseModel):
    max_results: int = 20
    custom_keywords: Optional[List[str]] = None
    session_name: Optional[str] = None


@router.post("/api/competitors/discover")
async def discover_competitors(req: DiscoverCompetitorsRequest, db: Session = Depends(get_db_session)):
    """F12-F13: Auto-discover competitors via web search."""
    already_known = {c.domain for c in db.query(Competitor).all()}

    # Build queries from master catalog
    from backend.competitor.discovery import build_discovery_queries
    products = db.query(Product).filter(Product.is_active == True).limit(50).all()
    titles = [p.canonical_title for p in products if p.canonical_title]
    manufacturers = list({p.manufacturer for p in products if p.manufacturer})
    models = list({p.model_number for p in products if p.model_number})
    queries = build_discovery_queries(titles, manufacturers, models, req.custom_keywords)

    async def do_discover():
        from backend.competitor.discovery import discover_competitors as _discover
        session_name = req.session_name or f"Discovery {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"

        async def ws_cb(event, data):
            await manager.broadcast({"event": event, **data})

        found = await _discover(
            queries=queries, max_results=req.max_results,
            already_known=already_known, progress_cb=ws_cb,
        )
        added = 0
        with session_scope() as s:
            for comp_data in found:
                existing = s.query(Competitor).filter(Competitor.domain == comp_data["domain"]).first()
                if not existing:
                    comp = Competitor(
                        domain=comp_data["domain"], name=comp_data["name"],
                        base_url=comp_data["base_url"], scan_session_name=session_name,
                    )
                    s.add(comp)
                    added += 1

        await manager.broadcast({"event": "discovery_complete", "added": added, "total": len(found)})

    asyncio.create_task(do_discover())
    return {"status": "discovery_started", "queries": len(queries)}


class BulkImportRequest(BaseModel):
    domains: List[str]
    session_name: Optional[str] = None


@router.post("/api/competitors/bulk-import")
async def bulk_import_competitors(req: BulkImportRequest, db: Session = Depends(get_db_session)):
    """F69: Import a list of competitor domains."""
    from backend.competitor.discovery import bulk_import_competitors as _bulk
    parsed = await _bulk(req.domains)
    added = 0
    session_name = req.session_name or f"Bulk Import {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    for comp_data in parsed:
        existing = db.query(Competitor).filter(Competitor.domain == comp_data["domain"]).first()
        if not existing:
            db.add(Competitor(
                domain=comp_data["domain"], name=comp_data["name"],
                base_url=comp_data["base_url"], scan_session_name=session_name,
            ))
            added += 1
    db.commit()
    return {"added": added, "parsed": len(parsed)}


@router.get("/api/competitors")
def list_competitors(
    page: int = 1, per_page: int = 50,
    db: Session = Depends(get_db_session)
):
    """F14: List all tracked competitors with scan history."""
    total = db.query(func.count(Competitor.id)).scalar() or 0
    competitors = (
        db.query(Competitor).order_by(Competitor.domain)
        .offset((page - 1) * per_page).limit(per_page).all()
    )
    return {
        "total": total,
        "competitors": [
            {
                "id": c.id, "domain": c.domain, "name": c.name, "base_url": c.base_url,
                "first_scanned_at": c.first_scanned_at.isoformat() if c.first_scanned_at else None,
                "last_scanned_at": c.last_scanned_at.isoformat() if c.last_scanned_at else None,
                "total_matching_products": c.total_matching_products,
                "scan_session_name": c.scan_session_name,
                "is_active": c.is_active,
                "scan_count": len(c.scans),
            }
            for c in competitors
        ],
    }


@router.get("/api/competitors/{competitor_id}")
def get_competitor(competitor_id: int, db: Session = Depends(get_db_session)):
    comp = db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")
    matches = (
        db.query(CompetitorProductMatch)
        .filter(CompetitorProductMatch.competitor_id == competitor_id, CompetitorProductMatch.is_active == True)
        .order_by(CompetitorProductMatch.competitor_price).all()
    )
    return {
        "id": comp.id, "domain": comp.domain, "name": comp.name, "base_url": comp.base_url,
        "first_scanned_at": comp.first_scanned_at.isoformat() if comp.first_scanned_at else None,
        "last_scanned_at": comp.last_scanned_at.isoformat() if comp.last_scanned_at else None,
        "total_matching_products": comp.total_matching_products,
        "is_active": comp.is_active,
        "scans": [
            {"id": s.id, "session_name": s.session_name, "status": s.status,
             "started_at": s.started_at.isoformat() if s.started_at else None,
             "products_found": s.products_found, "matches_found": s.matches_found}
            for s in comp.scans
        ],
        "matches": [
            {"id": m.id, "product_id": m.master_product_id, "url": m.competitor_url,
             "title": m.competitor_title, "price": m.competitor_price,
             "match_type": m.match_type, "confidence": m.match_confidence,
             "in_stock": m.in_stock, "is_similar": m.is_similar,
             "scanned_at": m.scanned_at.isoformat() if m.scanned_at else None}
            for m in matches
        ],
    }


class StartCompetitorScanRequest(BaseModel):
    competitor_ids: List[int]
    session_name: Optional[str] = None
    criteria: Optional[dict] = None
    find_similar: bool = False
    max_pages: int = 100


@router.post("/api/competitors/scan")
async def start_competitor_scan(req: StartCompetitorScanRequest, db: Session = Depends(get_db_session)):
    """F14-F15: Scan one or more competitor sites."""
    session_name = req.session_name or f"Competitor Scan {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"

    async def do_scans():
        from backend.competitor.scraper import run_competitor_scan
        for cid in req.competitor_ids:
            try:
                result = await run_competitor_scan(
                    competitor_id=cid,
                    session_name=session_name,
                    criteria_dict=req.criteria,
                    find_similar=req.find_similar,
                    max_pages=req.max_pages,
                    progress_callbacks=[lambda e, d: manager.broadcast({"event": e, **d})],
                )
                await manager.broadcast({"event": "competitor_scan_complete", **result})
            except Exception as exc:
                await manager.broadcast({"event": "competitor_scan_error", "competitor_id": cid, "error": str(exc)})

    asyncio.create_task(do_scans())
    return {"status": "scan_started", "competitor_ids": req.competitor_ids, "session_name": session_name}


@router.delete("/api/competitors/{competitor_id}")
def delete_competitor(competitor_id: int, db: Session = Depends(get_db_session)):
    comp = db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")
    comp.is_active = False
    return {"status": "deactivated"}


@router.put("/api/competitors/{competitor_id}")
def update_competitor(competitor_id: int, data: dict, db: Session = Depends(get_db_session)):
    comp = db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")
    for k in ("name", "base_url", "notes"):
        if k in data:
            setattr(comp, k, data[k])
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Price Comparison (F22-F26)
# ---------------------------------------------------------------------------

@router.get("/api/price-comparison")
def price_comparison_matrix(
    page: int = 1, per_page: int = 25,
    db: Session = Depends(get_db_session),
):
    """F26: Matrix of all products vs all competitors."""
    products = (
        db.query(Product).filter(Product.is_active == True)
        .order_by(Product.canonical_title)
        .offset((page - 1) * per_page).limit(per_page).all()
    )
    total = db.query(func.count(Product.id)).filter(Product.is_active == True).scalar() or 0
    competitors = db.query(Competitor).filter(Competitor.is_active == True).all()

    rows = []
    for p in products:
        row = {
            "product_id": p.id,
            "title": p.canonical_title,
            "our_price": p.price_canonical,
            "by_competitor": {},
        }
        for comp in competitors:
            match = next(
                (m for m in p.competitor_matches if m.competitor_id == comp.id and m.is_active),
                None
            )
            row["by_competitor"][comp.domain] = {
                "price": match.competitor_price if match else None,
                "url": match.competitor_url if match else None,
                "in_stock": match.in_stock if match else None,
            }
        rows.append(row)

    return {
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "competitors": [{"id": c.id, "domain": c.domain} for c in competitors],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Scheduler (F43-F47)
# ---------------------------------------------------------------------------

class CreateJobRequest(BaseModel):
    name: str
    job_type: str   # source_scan|competitor_scan|price_check|export|dedup
    target: Optional[str] = None
    schedule_type: str  # cron|daily|weekly|monthly|one_time|interval_minutes
    schedule_value: str
    config_json: Optional[str] = None


@router.get("/api/scheduler/jobs")
def list_jobs():
    from backend.scheduler.scheduler import list_jobs as _list
    return {"jobs": _list()}


@router.post("/api/scheduler/jobs")
def create_job(req: CreateJobRequest):
    from backend.scheduler.scheduler import create_job as _create
    try:
        result = _create(
            name=req.name, job_type=req.job_type, target=req.target,
            schedule_type=req.schedule_type, schedule_value=req.schedule_value,
            config_json=req.config_json,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/scheduler/jobs/{job_id}")
def delete_job(job_id: int):
    from backend.scheduler.scheduler import delete_job as _delete
    _delete(job_id)
    return {"status": "deleted"}


@router.post("/api/scheduler/jobs/{job_id}/run-now")
def run_job_now(job_id: int):
    from backend.scheduler.scheduler import run_job_now as _run
    _run(job_id)
    return {"status": "queued"}


@router.put("/api/scheduler/jobs/{job_id}/toggle")
def toggle_job(job_id: int, active: bool = True):
    from backend.scheduler.scheduler import toggle_job as _toggle
    _toggle(job_id, active)
    return {"status": "updated", "active": active}


# ---------------------------------------------------------------------------
# Export (F39-F42)
# ---------------------------------------------------------------------------

@router.get("/api/export/products")
def export_products(
    fmt: str = "csv",
    include_competitors: bool = True,
    include_price_history: bool = False,
    db: Session = Depends(get_db_session),
):
    from backend.export.exporter import export_products_csv, export_products_xlsx, export_products_txt

    if fmt == "csv":
        data, filename = export_products_csv(triggered_by="user")
        return Response(content=data, media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    elif fmt == "xlsx":
        data, filename = export_products_xlsx(
            include_competitors=include_competitors,
            include_price_history=include_price_history,
            triggered_by="user",
        )
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    elif fmt == "txt":
        data, filename = export_products_txt(triggered_by="user")
        return Response(content=data, media_type="text/plain",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}. Use csv, xlsx, or txt")


@router.get("/api/export/history")
def export_history(page: int = 1, per_page: int = 20, db: Session = Depends(get_db_session)):
    """F42: Export history log."""
    total = db.query(func.count(ExportRecord.id)).scalar() or 0
    records = (
        db.query(ExportRecord).order_by(ExportRecord.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page).all()
    )
    return {
        "total": total,
        "records": [
            {"id": r.id, "export_type": r.export_type, "filename": r.filename,
             "scope": r.scope, "row_count": r.row_count, "triggered_by": r.triggered_by,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# Reports (F61-F63)
# ---------------------------------------------------------------------------

@router.get("/api/reports/price-disparity", response_class=HTMLResponse)
def report_price_disparity(threshold: float = 5.0):
    from backend.reports.reporter import price_disparity_report
    return HTMLResponse(content=price_disparity_report(threshold))


@router.get("/api/reports/competitor/{competitor_id}", response_class=HTMLResponse)
def report_competitor(competitor_id: int):
    from backend.reports.reporter import competitor_report
    return HTMLResponse(content=competitor_report(competitor_id))


@router.get("/api/reports/summary", response_class=HTMLResponse)
def report_summary(days: int = 7):
    from backend.reports.reporter import summary_report
    return HTMLResponse(content=summary_report(days))


@router.get("/api/reports/price-comparison/{product_id}", response_class=HTMLResponse)
def report_price_comparison(product_id: int):
    from backend.reports.reporter import price_comparison_report
    return HTMLResponse(content=price_comparison_report(product_id))


# ---------------------------------------------------------------------------
# AI Categorization (F64)
# ---------------------------------------------------------------------------

class CategorizeRequest(BaseModel):
    product_ids: List[int]


@router.post("/api/ai/categorize")
async def ai_categorize(req: CategorizeRequest):
    async def do_categorize():
        from backend.ai.categorizer import bulk_categorize
        results = bulk_categorize(req.product_ids)
        count = sum(1 for r in results.values() if r)
        await manager.broadcast({"event": "ai_categorize_complete", "categorized": count, "total": len(req.product_ids)})

    asyncio.create_task(do_categorize())
    return {"status": "categorization_started", "product_count": len(req.product_ids)}


# ---------------------------------------------------------------------------
# Tags & Notes (F71)
# ---------------------------------------------------------------------------

class AddTagRequest(BaseModel):
    tag: str


@router.post("/api/products/{product_id}/tags")
def add_tag(product_id: int, req: AddTagRequest, db: Session = Depends(get_db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    existing = next((t for t in product.tags if t.tag == req.tag.strip()), None)
    if not existing:
        db.add(ProductTag(product_id=product_id, tag=req.tag.strip()))
    return {"status": "ok"}


@router.delete("/api/products/{product_id}/tags/{tag}")
def remove_tag(product_id: int, tag: str, db: Session = Depends(get_db_session)):
    tag_obj = db.query(ProductTag).filter(ProductTag.product_id == product_id, ProductTag.tag == tag).first()
    if tag_obj:
        db.delete(tag_obj)
    return {"status": "ok"}


class AddNoteRequest(BaseModel):
    note: str


@router.post("/api/products/{product_id}/notes")
def add_note(product_id: int, req: AddNoteRequest, db: Session = Depends(get_db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.add(ProductNote(product_id=product_id, note_text=req.note.strip(), created_by="user"))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Webhooks (F72)
# ---------------------------------------------------------------------------

class WebhookConfig(BaseModel):
    url: str
    events: List[str]   # price_alert|scan_complete|competitor_scan_complete
    secret: Optional[str] = None


@router.put("/api/settings/webhook")
def configure_webhook(req: WebhookConfig):
    config.set("webhook", "url", req.url)
    config.set("webhook", "events", req.events)
    if req.secret:
        config.set("webhook", "secret", req.secret)
    return {"status": "webhook configured"}


@router.get("/api/settings/webhook")
def get_webhook():
    return {
        "url": config.get("webhook", "url", default=""),
        "events": config.get("webhook", "events", default=[]),
    }


# ---------------------------------------------------------------------------
# Settings (F56)
# ---------------------------------------------------------------------------

@router.get("/api/settings")
def get_settings():
    return config.all()


class UpdateSettingRequest(BaseModel):
    keys: List[str]
    value: Any


@router.put("/api/settings")
def update_setting(req: UpdateSettingRequest):
    config.set(*req.keys, req.value)
    return {"status": "saved"}


@router.get("/api/settings/db-health")
def db_health():
    return db_health_check()


# ---------------------------------------------------------------------------
# Task Manager — active/recent task list
# ---------------------------------------------------------------------------

@router.get("/api/tasks")
def list_tasks():
    return {"tasks": _task_manager.get_all()}


# ---------------------------------------------------------------------------
# Scan Cycle Status — prevents re-scanning before a full cycle is approved
# ---------------------------------------------------------------------------

_CYCLE_KEY = "scan_cycle_status"

def _read_cycle(db: Session) -> dict:
    row = db.query(AppSetting).filter(AppSetting.key == _CYCLE_KEY).first()
    if row and row.value:
        try:
            return json.loads(row.value)
        except Exception:
            pass
    return {"status": "idle", "domains_started": [], "domains_complete": [], "dedup_done": False, "last_complete_at": None}


def _write_cycle(db: Session, state: dict) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == _CYCLE_KEY).first()
    if row:
        row.value = json.dumps(state)
    else:
        db.add(AppSetting(key=_CYCLE_KEY, value=json.dumps(state), description="Parallel scan cycle state"))


@router.get("/api/scan/cycle-status")
def get_cycle_status(db: Session = Depends(get_db_session)):
    return _read_cycle(db)


@router.post("/api/scan/cycle/approve")
def approve_cycle(db: Session = Depends(get_db_session)):
    state = _read_cycle(db)
    state["status"] = "complete"
    state["last_complete_at"] = datetime.utcnow().isoformat()
    _write_cycle(db, state)
    return {"status": "approved"}


# ---------------------------------------------------------------------------
# Parallel Source Scan — spawns one task per enabled domain + dedup after
# ---------------------------------------------------------------------------

@router.post("/api/scan/all-sources")
async def start_parallel_scan(db: Session = Depends(get_db_session)):
    state = _read_cycle(db)
    if state.get("status") in ("scanning", "dedup_running", "review_pending"):
        raise HTTPException(status_code=409, detail="A scan cycle is already in progress")

    sites = [s for s in config.get("source_sites", default=[]) if s.get("enabled")]
    if not sites:
        raise HTTPException(status_code=400, detail="No enabled source sites configured")

    # Reset cycle state
    state = {
        "status": "scanning",
        "domains_started": [s["domain"] for s in sites],
        "domains_complete": [],
        "dedup_done": False,
        "last_complete_at": state.get("last_complete_at"),
    }
    _write_cycle(db, state)
    db.commit()

    async def _broadcast_cycle(new_state: dict) -> None:
        await manager.broadcast({"event": "cycle_status", **new_state})

    domain_task_ids: List[str] = []

    for site in sites:
        domain = site["domain"]

        async def _scan_domain(s=site) -> None:
            scan_sess = ScanSession(
                name=f"Parallel scan — {s['name']} {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                session_type="source", target=s["domain"], status="pending",
            )
            with session_scope() as sess_db:
                sess_db.add(scan_sess)
                sess_db.flush()
                scan_id = scan_sess.id

            async def ws_cb(event: str, data: dict) -> None:
                await manager.broadcast({"event": event, "session_id": scan_id, **data})

            await run_source_scan(scan_session_id=scan_id, site_filter=s["domain"], progress_callbacks=[ws_cb])

            with session_scope() as upd_db:
                cyc = _read_cycle(upd_db)
                if s["domain"] not in cyc["domains_complete"]:
                    cyc["domains_complete"].append(s["domain"])
                if set(cyc["domains_complete"]) >= set(cyc["domains_started"]):
                    cyc["status"] = "dedup_running"
                _write_cycle(upd_db, cyc)
            await _broadcast_cycle(cyc)

        tid = _task_manager.submit(f"Scan {domain}", _scan_domain)
        domain_task_ids.append(tid)

    async def _run_dedup() -> None:
        with session_scope() as dd_db:
            engine = DeduplicationEngine()
            stats = engine.run(dd_db, None)
            cyc = _read_cycle(dd_db)
            cyc["dedup_done"] = True
            cyc["status"] = "review_pending"
            _write_cycle(dd_db, cyc)
        await manager.broadcast({"event": "dedup_complete", "stats": stats})
        await _broadcast_cycle(cyc)

    _task_manager.submit("Deduplication", _run_dedup, depends_on=domain_task_ids)

    return {"status": "started", "domains": [s["domain"] for s in sites], "task_ids": domain_task_ids}


# ---------------------------------------------------------------------------
# Domain Comparison — products on 2+ source domains with field differences
# ---------------------------------------------------------------------------

@router.get("/api/domain-comparison")
def get_domain_comparison(
    page: int = 1,
    per_page: int = 50,
    show_all: bool = False,
    db: Session = Depends(get_db_session),
):
    # Product IDs present on 2+ distinct active source sites
    multi_domain_ids = (
        db.query(ProductSource.product_id)
        .filter(ProductSource.is_active == True)
        .group_by(ProductSource.product_id)
        .having(func.count(func.distinct(ProductSource.source_site)) >= 2)
        .subquery()
    )

    products = (
        db.query(Product)
        .filter(Product.id.in_(multi_domain_ids), Product.is_active == True)
        .order_by(Product.canonical_title)
        .all()
    )

    results = []
    for product in products:
        # Latest active source per site
        site_sources: Dict[str, Any] = {}
        for src in sorted(product.sources, key=lambda s: s.scraped_at or datetime.min):
            if src.is_active:
                site_sources[src.source_site] = src

        if len(site_sources) < 2:
            continue

        sites_data = {
            site: {
                "title": src.source_title,
                "price": src.source_price,
                "manufacturer": src.source_manufacturer,
                "model_number": src.source_model_number,
                "sku": src.source_sku,
                "url": src.source_url,
                "scraped_at": src.scraped_at.isoformat() if src.scraped_at else None,
            }
            for site, src in site_sources.items()
        }

        diff_fields: List[str] = []
        for field in ("title", "price", "manufacturer", "model_number", "sku"):
            vals = [str(sites_data[s][field]) for s in site_sources if sites_data[s][field] is not None]
            if len(set(vals)) > 1:
                diff_fields.append(field)

        if not show_all and not diff_fields:
            continue

        results.append({
            "product_id": product.id,
            "canonical_title": product.canonical_title,
            "manufacturer": product.manufacturer,
            "model_number": product.model_number,
            "category": product.category,
            "domains": sites_data,
            "diff_fields": diff_fields,
        })

    total = len(results)
    start = (page - 1) * per_page
    page_data = results[start: start + per_page]

    all_domains = sorted({site for r in results for site in r["domains"]})

    return {
        "products": page_data,
        "total": total,
        "page": page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "all_domains": all_domains,
    }
