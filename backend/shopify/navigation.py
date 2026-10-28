"""Shopify navigation scanning, cross-store comparison, and menu/catalog audits."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote, urlparse


MENUS_QUERY = """
query Menus($cursor: String) {
  menus(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      handle
      title
      items {
        id title type url resourceId
        items {
          id title type url resourceId
          items { id title type url resourceId }
        }
      }
    }
  }
}
"""


async def scan_menus(client) -> List[Dict[str, Any]]:
    menus: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        data = await client.graphql(MENUS_QUERY, {"cursor": cursor})
        connection = data.get("menus") or {}
        menus.extend(connection.get("nodes") or [])
        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return menus
        cursor = page.get("endCursor")


def _resource_handle(url: str, kind: str) -> Optional[str]:
    if not url:
        return None
    path = unquote(urlparse(url).path)
    marker = f"/{kind}/"
    if marker not in path:
        return None
    value = path.split(marker, 1)[1].strip("/").split("/", 1)[0]
    return value or None


def flatten_menus(menus: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []

    def walk(items, menu, parents):
        for item in items or []:
            title = item.get("title") or ""
            path = parents + [title]
            item_type = (item.get("type") or "").upper()
            flattened.append({
                "item_id": item.get("id"),
                "resource_id": str(item["resourceId"]) if item.get("resourceId") is not None else None,
                "menu_handle": menu.get("handle") or "",
                "menu_title": menu.get("title") or menu.get("handle") or "",
                "path": " › ".join(path),
                "title": title,
                "type": item_type,
                "url": item.get("url") or "",
                "product_handle": _resource_handle(item.get("url") or "", "products") if item_type == "PRODUCT" else None,
                "collection_handle": _resource_handle(item.get("url") or "", "collections") if item_type == "COLLECTION" else None,
            })
            walk(item.get("items"), menu, path)

    for menu in menus:
        walk(menu.get("items"), menu, [])
    return flattened


def _lookup(mapping: Dict[Any, Any], value: Any) -> Any:
    if value is None:
        return None
    direct = mapping.get(value) or mapping.get(str(value))
    if direct is not None:
        return direct
    resource_id = str(value)
    if resource_id.startswith("gid://"):
        legacy = resource_id.rsplit("/", 1)[-1]
        return mapping.get(legacy) or mapping.get(int(legacy) if legacy.isdigit() else legacy)
    return None


def analyze_menus(menus: List[Dict[str, Any]], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    items = flatten_menus(menus)
    products = snapshot.get("products") or {}
    products_by_id = snapshot.get("products_by_id") or {}
    collections = snapshot.get("collections") or {}
    product_collections = snapshot.get("product_collections") or {}
    collection_products = snapshot.get("collection_products") or {}

    product_by_resource: Dict[str, str] = {}
    for handle, product in products.items():
        product_by_resource[str(product.get("id"))] = handle
        if product.get("admin_graphql_api_id"):
            product_by_resource[str(product["admin_graphql_api_id"])] = handle
    for product_id, handle in products_by_id.items():
        product_by_resource[str(product_id)] = handle

    collection_by_handle = {
        col.get("handle"): col for col in collections.values() if col.get("handle")
    }
    occurrences: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    represented = set()
    unresolved = []
    represented_collections = []

    for item in items:
        if item["type"] == "PRODUCT":
            handle = item["product_handle"] or product_by_resource.get(str(item.get("resource_id")))
            if not handle or handle not in products:
                unresolved.append(item)
                continue
            represented.add(handle)
            occurrences[handle].append(item)
        elif item["type"] == "COLLECTION":
            collection = _lookup(collections, item.get("resource_id"))
            if not collection and item.get("collection_handle"):
                collection = collection_by_handle.get(item["collection_handle"])
            if not collection:
                continue
            collection_id = collection.get("id")
            represented_collections.append({
                "id": collection_id,
                "title": collection.get("title"),
                "menu_handle": item["menu_handle"],
                "path": item["path"],
            })
            product_ids = _lookup(collection_products, collection_id) or []
            if not product_ids:
                product_ids = [
                    pid for pid, cids in product_collections.items()
                    if str(collection_id) in {str(cid) for cid in (cids or [])}
                ]
            for product_id in product_ids:
                handle = product_by_resource.get(str(product_id))
                if handle:
                    represented.add(handle)

    missing = []
    for handle, product in products.items():
        if handle not in represented:
            missing.append({
                "id": product.get("id"),
                "handle": handle,
                "title": product.get("title") or handle,
                "status": product.get("status"),
            })
    missing.sort(key=lambda p: (p["title"] or "").lower())

    duplicates = []
    for handle, links in occurrences.items():
        if len(links) < 2:
            continue
        product = products.get(handle) or {}
        duplicates.append({
            "handle": handle,
            "title": product.get("title") or handle,
            "count": len(links),
            "occurrences": links,
        })
    duplicates.sort(key=lambda p: (-p["count"], p["title"].lower()))

    return {
        "missing_products": missing,
        "duplicate_products": duplicates,
        "unresolved_product_items": unresolved,
        "represented_collections": represented_collections,
        "counts": {
            "menus": len(menus),
            "menu_items": len(items),
            "catalog_products": len(products),
            "represented_products": len(represented),
            "missing_products": len(missing),
            "duplicate_products": len(duplicates),
            "unresolved_product_items": len(unresolved),
        },
    }


def compare_menus(store_menus: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    domains = list(store_menus)
    menu_handles = sorted({
        menu.get("handle") or "" for menus in store_menus.values() for menu in menus
    })
    menu_rows = []
    for handle in menu_handles:
        values = {}
        for domain, menus in store_menus.items():
            menu = next((m for m in menus if (m.get("handle") or "") == handle), None)
            if menu:
                values[domain] = {
                    "title": menu.get("title") or handle,
                    "item_count": len(flatten_menus([menu])),
                }
        missing = [domain for domain in domains if domain not in values]
        titles = {(v.get("title") or "").strip().casefold() for v in values.values()}
        menu_rows.append({
            "handle": handle,
            "stores": values,
            "missing": missing,
            "different": bool(missing) or len(titles) > 1,
        })

    grouped: Dict[tuple, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for domain, menus in store_menus.items():
        for item in flatten_menus(menus):
            key = (item["menu_handle"], item["path"])
            grouped[key][domain] = item

    item_rows = []
    for (menu_handle, path), values in grouped.items():
        signatures = {
            (v["title"].strip().casefold(), v["type"], v["url"].strip())
            for v in values.values()
        }
        missing = [domain for domain in domains if domain not in values]
        item_rows.append({
            "menu_handle": menu_handle,
            "path": path,
            "stores": values,
            "missing": missing,
            "different": bool(missing) or len(signatures) > 1,
        })
    item_rows.sort(key=lambda row: (row["menu_handle"], row["path"]))
    return {
        "domains": domains,
        "menus": menu_rows,
        "items": item_rows,
        "difference_count": sum(row["different"] for row in menu_rows + item_rows),
    }
