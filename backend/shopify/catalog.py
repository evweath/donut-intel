"""Live Shopify catalog snapshots and field-level cross-store comparison."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


PRODUCT_FIELDS = {
    "title": "Title",
    "body_html": "Description (HTML)",
    "vendor": "Vendor",
    "product_type": "Product type",
    "handle": "Handle / URL slug",
    "status": "Status",
    "tags": "Tags",
    "template_suffix": "Theme template",
    "published_scope": "Published scope",
    "options": "Options",
    "variants": "Variants, prices, SKUs and inventory",
    "images": "Images",
    "metafields": "Metafields",
    "collections": "Collection membership",
}

_READ_ONLY_VARIANT_KEYS = {
    "id", "product_id", "inventory_item_id", "admin_graphql_api_id",
    "created_at", "updated_at",
}
_READ_ONLY_IMAGE_KEYS = {
    "id", "product_id", "admin_graphql_api_id", "created_at", "updated_at",
    "variant_ids",
}


async def scan_store(client, progress_cb: Optional[Callable[[str, int, int], None]] = None) -> Dict[str, Any]:
    def progress(stage: str, done: int = 0, total: int = 0):
        if progress_cb:
            progress_cb(stage, done, total)

    snapshot: Dict[str, Any] = {
        "shop": {},
        "products": {},
        "products_by_id": {},
        "collections": {},
        "collects": [],
        "product_collections": {},
        "collection_products": {},
        "metafields": {},
        "menus": [],
        "menu_error": None,
    }

    progress("shop")
    snapshot["shop"] = await client.get_shop()

    progress("products")
    count = 0
    for status in ("active", "draft", "archived"):
        async for product in client.iter_products(status=status):
            if product["id"] in snapshot["products_by_id"]:
                continue
            handle = product.get("handle") or str(product.get("id"))
            snapshot["products"][handle] = product
            snapshot["products_by_id"][product["id"]] = handle
            count += 1
            if count % 100 == 0:
                progress("products", count, count)
    progress("products", count, count)

    progress("collections")
    custom = await client.get_custom_collections()
    smart = await client.get_smart_collections()
    for collection in custom:
        collection["_type"] = "custom"
        snapshot["collections"][collection["id"]] = collection
    for collection in smart:
        collection["_type"] = "smart"
        snapshot["collections"][collection["id"]] = collection

    progress("collects")
    collects = await client.get_collects()
    snapshot["collects"] = collects
    for collect in collects:
        product_id = collect["product_id"]
        collection_id = collect["collection_id"]
        snapshot["product_collections"].setdefault(product_id, []).append(collection_id)
        snapshot["collection_products"].setdefault(collection_id, []).append(product_id)

    for collection in smart:
        collection_id = collection["id"]
        for product in await client.get_smart_collection_products(collection_id):
            product_id = product["id"]
            if product_id not in snapshot["collection_products"].setdefault(collection_id, []):
                snapshot["collection_products"][collection_id].append(product_id)
            if collection_id not in snapshot["product_collections"].setdefault(product_id, []):
                snapshot["product_collections"][product_id].append(collection_id)

    product_ids = list(snapshot["products_by_id"])
    progress("metafields", 0, len(product_ids))
    try:
        metafields = await client.get_all_product_metafields()
        for field in metafields:
            if field.get("owner_id") in snapshot["products_by_id"]:
                snapshot["metafields"].setdefault(field["owner_id"], []).append(field)
        progress("metafields", len(product_ids), len(product_ids))
    except Exception as exc:
        logger.warning("Bulk metafield read failed; falling back to per-product reads: %s", exc)
        for index, product_id in enumerate(product_ids, 1):
            metafields = await client.get_product_metafields(product_id)
            if metafields:
                snapshot["metafields"][product_id] = metafields
            if index % 25 == 0 or index == len(product_ids):
                progress("metafields", index, len(product_ids))

    return snapshot


def _lookup(mapping: Dict[Any, Any], key: Any) -> Any:
    if key is None:
        return None
    return mapping.get(key) or mapping.get(str(key))


def _without_keys(items: List[Dict[str, Any]], ignored: set) -> List[Dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if key not in ignored}
        for item in items or []
    ]


def _variant_key(variant: Dict[str, Any]) -> str:
    if variant.get("sku"):
        return f"sku:{variant['sku']}"
    options = "|".join(str(variant.get(f"option{i}") or "") for i in (1, 2, 3))
    if options.strip("|"):
        return f"options:{options}"
    return f"title:{variant.get('title') or variant.get('id') or ''}"


def product_details(product: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    product_id = product.get("id")
    tags = [tag.strip() for tag in (product.get("tags") or "").split(",") if tag.strip()]
    variants = _without_keys(product.get("variants") or [], _READ_ONLY_VARIANT_KEYS)
    variants.sort(key=_variant_key)
    images = _without_keys(product.get("images") or [], _READ_ONLY_IMAGE_KEYS)
    images.sort(key=lambda image: (image.get("position") or 0, image.get("src") or ""))
    options = _without_keys(product.get("options") or [], {"id", "product_id"})
    options.sort(key=lambda option: option.get("position") or 0)

    metafields = _lookup(snapshot.get("metafields") or {}, product_id) or []
    normalized_metafields = sorted([
        {
            "namespace": field.get("namespace"),
            "key": field.get("key"),
            "type": field.get("type"),
            "value": field.get("value"),
        }
        for field in metafields
    ], key=lambda field: (field["namespace"] or "", field["key"] or ""))

    collection_titles = []
    for collection_id in _lookup(snapshot.get("product_collections") or {}, product_id) or []:
        collection = _lookup(snapshot.get("collections") or {}, collection_id)
        if collection and collection.get("title"):
            collection_titles.append(collection["title"])

    return {
        "title": product.get("title"),
        "body_html": product.get("body_html"),
        "vendor": product.get("vendor"),
        "product_type": product.get("product_type"),
        "handle": product.get("handle"),
        "status": product.get("status"),
        "tags": sorted(tags, key=str.casefold),
        "template_suffix": product.get("template_suffix"),
        "published_scope": product.get("published_scope"),
        "options": options,
        "variants": variants,
        "images": images,
        "metafields": normalized_metafields,
        "collections": sorted(collection_titles, key=str.casefold),
    }


def _same(values: List[Any]) -> bool:
    encoded = [json.dumps(value, sort_keys=True, default=str) for value in values]
    return len(set(encoded)) <= 1


def compare_catalogs(
    snapshots: Dict[str, Dict[str, Any]],
    search: str = "",
    differences_only: bool = False,
) -> List[Dict[str, Any]]:
    domains = list(snapshots)
    handles = sorted({
        handle for snapshot in snapshots.values() for handle in (snapshot.get("products") or {})
    })
    needle = search.strip().casefold()
    groups = []

    for handle in handles:
        products = {
            domain: (snapshot.get("products") or {}).get(handle)
            for domain, snapshot in snapshots.items()
        }
        present = {domain: product for domain, product in products.items() if product}
        first = next(iter(present.values()))
        haystack = " ".join([
            handle,
            first.get("title") or "",
            first.get("vendor") or "",
            " ".join(variant.get("sku") or "" for variant in first.get("variants") or []),
        ]).casefold()
        if needle and needle not in haystack:
            continue

        details = {
            domain: product_details(product, snapshots[domain])
            for domain, product in present.items()
        }
        missing = [domain for domain in domains if domain not in present]
        differences = []
        for field, label in PRODUCT_FIELDS.items():
            values = {domain: value.get(field) for domain, value in details.items()}
            if len(values) > 1 and not _same(list(values.values())):
                differences.append({"field": field, "label": label, "values": values})
        different = bool(missing) or bool(differences)
        if differences_only and not different:
            continue
        groups.append({
            "handle": handle,
            "title": first.get("title") or handle,
            "stores": products,
            "details": details,
            "missing": missing,
            "different": different,
            "differences": differences,
            "difference_fields": [difference["field"] for difference in differences],
        })

    groups.sort(key=lambda group: ((group["title"] or "").casefold(), group["handle"]))
    return groups
