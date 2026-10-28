"""Live Shopify catalog, navigation, comparison, and transfer endpoints."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import config
from backend.shopify import scan_cache
from backend.shopify.catalog import compare_catalogs, scan_store
from backend.shopify.client import ShopifyClient
from backend.shopify.navigation import analyze_menus, compare_menus, scan_menus
from backend.shopify.transfer import build_transfer_preview, execute_transfer

router = APIRouter()
_ANY_AGE_DAYS = 10_000_000

_scan_state: Dict[str, Any] = {
    "running": False,
    "finished": False,
    "current_domain": None,
    "stage": None,
    "done": 0,
    "total": 0,
    "results": {},
}
_scan_task = None


class CatalogScanRequest(BaseModel):
    domains: Optional[List[str]] = None


def _selected_domains(domains: Optional[List[str]] = None) -> List[str]:
    configured = {
        site.get("domain"): site for site in config.get("source_sites", default=[])
        if site.get("domain")
    }
    if domains:
        unknown = [domain for domain in domains if domain not in configured]
        if unknown:
            raise HTTPException(status_code=404, detail=f"Unknown source site(s): {', '.join(unknown)}")
        return list(dict.fromkeys(domains))
    return [domain for domain, site in configured.items() if site.get("enabled", True)]


def _domain_param(domains: Optional[str]) -> List[str]:
    selected = [domain.strip() for domain in (domains or "").split(",") if domain.strip()]
    return _selected_domains(selected or None)


def _load_available_snapshots(domains: List[str]):
    snapshots = {}
    missing = []
    for domain in domains:
        snapshot = scan_cache.load_snapshot(domain, max_age_days=_ANY_AGE_DAYS)
        if snapshot is None:
            missing.append(domain)
        else:
            snapshots[domain] = snapshot
    if not snapshots:
        raise HTTPException(
            status_code=409,
            detail=f"Scan required before comparison: {', '.join(missing)}",
        )
    return snapshots, missing


def _load_snapshots(domains: List[str]) -> Dict[str, Dict[str, Any]]:
    snapshots, missing = _load_available_snapshots(domains)
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"Scan required before comparison: {', '.join(missing)}",
        )
    return snapshots


@router.get("/api/store-catalog/stores")
def catalog_stores():
    stores = []
    for domain in _selected_domains():
        site = next(site for site in config.get("source_sites", default=[]) if site.get("domain") == domain)
        info = scan_cache.scan_info(domain, max_age_days=_ANY_AGE_DAYS)
        stores.append({
            "domain": domain,
            "name": site.get("name") or domain,
            "credentials_configured": bool(
                (site.get("shopify_store_url") and site.get("shopify_access_token"))
                or (site.get("shopify_store_url") and site.get("shopify_client_id") and site.get("shopify_client_secret"))
            ),
            "scan": info,
        })
    return {"stores": stores, "scan": _scan_state}


@router.post("/api/store-catalog/scan")
async def start_catalog_scan(req: CatalogScanRequest):
    global _scan_task
    if _scan_state["running"]:
        raise HTTPException(status_code=409, detail="A store catalog scan is already running")
    domains = _selected_domains(req.domains)
    if not domains:
        raise HTTPException(status_code=422, detail="No enabled stores selected")
    _scan_state.clear()
    _scan_state.update({
        "running": True,
        "finished": False,
        "current_domain": None,
        "stage": "queued",
        "done": 0,
        "total": len(domains),
        "results": {},
    })

    async def job():
        for domain in domains:
            _scan_state["current_domain"] = domain
            _scan_state["stage"] = "credentials"
            try:
                from backend.api.routes import _get_site_credentials
                store_url, token = await _get_site_credentials(domain)

                def progress(stage, done=0, total=0):
                    _scan_state["stage"] = stage
                    _scan_state["stage_done"] = done
                    _scan_state["stage_total"] = total

                async with ShopifyClient(store_url, token) as client:
                    snapshot = await scan_store(client, progress_cb=progress)
                    _scan_state["stage"] = "menus"
                    try:
                        snapshot["menus"] = await scan_menus(client)
                    except Exception as exc:
                        snapshot["menus"] = []
                        snapshot["menu_error"] = str(exc)
                scan_cache.save_scan(domain, snapshot)
                _scan_state["results"][domain] = {
                    "status": "ok",
                    "products": len(snapshot["products"]),
                    "menus": len(snapshot["menus"]),
                    "menu_error": snapshot.get("menu_error"),
                }
            except Exception as exc:
                _scan_state["results"][domain] = {"status": "error", "error": str(exc)}
            _scan_state["done"] += 1
        _scan_state["running"] = False
        _scan_state["finished"] = True
        _scan_state["current_domain"] = None
        _scan_state["stage"] = "complete"

    _scan_task = asyncio.create_task(job())
    return {"status": "started", "domains": domains, "total": len(domains)}


@router.get("/api/store-catalog/scan/status")
def catalog_scan_status():
    return _scan_state


@router.get("/api/store-catalog/menus")
def catalog_menus(domains: Optional[str] = None):
    selected = _domain_param(domains)
    snapshots, unavailable = _load_available_snapshots(selected)
    stores = {}
    for domain, snapshot in snapshots.items():
        menus = snapshot.get("menus") or []
        stores[domain] = {
            "menus": menus,
            "menu_error": snapshot.get("menu_error"),
            "analysis": analyze_menus(menus, snapshot),
        }
    return {"domains": selected, "stores": stores, "unavailable": unavailable}


@router.get("/api/store-catalog/menu-comparison")
def catalog_menu_comparison(domains: Optional[str] = None):
    selected = _domain_param(domains)
    if len(selected) < 2:
        raise HTTPException(status_code=422, detail="Select at least two stores to compare menus")
    snapshots, unavailable = _load_available_snapshots(selected)
    result = compare_menus({domain: snapshot.get("menus") or [] for domain, snapshot in snapshots.items()})
    result["unavailable"] = unavailable
    return result


@router.get("/api/store-catalog/products")
def catalog_products(
    domains: Optional[str] = None,
    search: str = "",
    differences_only: bool = False,
    page: int = 1,
    per_page: int = 25,
):
    selected = _domain_param(domains)
    if len(selected) < 2:
        raise HTTPException(status_code=422, detail="Select at least two stores to compare products")
    snapshots, unavailable = _load_available_snapshots(selected)
    groups = compare_catalogs(snapshots, search=search, differences_only=differences_only)
    per_page = max(1, min(per_page, 100))
    page = max(1, page)
    total = len(groups)
    return {
        "domains": selected,
        "unavailable": unavailable,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "products": groups[(page - 1) * per_page:page * per_page],
    }


class CatalogTransferRequest(BaseModel):
    source_domain: str
    destination_domain: str
    handle: str
    fields: List[str]
    create_if_missing: bool = False
    replace_images: bool = False
    confirm: bool = False


def _transfer_context(req: CatalogTransferRequest):
    if req.source_domain == req.destination_domain:
        raise HTTPException(status_code=422, detail="Source and destination stores must be different")
    domains = _selected_domains([req.source_domain, req.destination_domain])
    snapshots = _load_snapshots(domains)
    try:
        preview = build_transfer_preview(
            snapshots[req.source_domain],
            snapshots[req.destination_domain],
            req.handle,
            req.fields,
            create_if_missing=req.create_if_missing,
            replace_images=req.replace_images,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return snapshots, preview


@router.post("/api/store-catalog/transfer/preview")
def catalog_transfer_preview(req: CatalogTransferRequest):
    _, preview = _transfer_context(req)
    return preview


@router.post("/api/store-catalog/transfer/execute")
async def catalog_transfer_execute(req: CatalogTransferRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Review the transfer and set confirm=true before executing")
    snapshots, preview = _transfer_context(req)
    if not preview["can_execute"]:
        raise HTTPException(status_code=409, detail="Destination product is missing; creation was not confirmed")
    from backend.api.routes import _get_site_credentials
    source_url, source_token = await _get_site_credentials(req.source_domain)
    destination_url, destination_token = await _get_site_credentials(req.destination_domain)
    try:
        result = await execute_transfer(
            source_url,
            source_token,
            destination_url,
            destination_token,
            snapshots[req.source_domain],
            snapshots[req.destination_domain],
            req.handle,
            req.fields,
            create_if_missing=req.create_if_missing,
            replace_images=req.replace_images,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if result.get("product"):
        destination_snapshot = snapshots[req.destination_domain]
        product = result["product"]
        new_handle = product.get("handle") or req.handle
        destination_snapshot.setdefault("products", {}).pop(req.handle, None)
        destination_snapshot["products"][new_handle] = product
        destination_snapshot.setdefault("products_by_id", {})[product["id"]] = new_handle
        scan_cache.save_scan(req.destination_domain, destination_snapshot)
    result["rescan_recommended"] = True
    return result
