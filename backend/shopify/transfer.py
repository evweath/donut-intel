"""Preview and execute field-selected transfers for one Shopify product."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .catalog import product_details
from .client import ShopifyClient

PRODUCT_INPUT_FIELDS = {
    "title", "body_html", "vendor", "product_type", "handle", "status",
    "tags", "template_suffix", "published_scope",
}
VARIANT_INPUT_FIELDS = {
    "price", "compare_at_price", "sku", "barcode", "weight", "weight_unit",
    "taxable", "requires_shipping", "inventory_policy", "fulfillment_service",
}
TRANSFER_FIELDS = PRODUCT_INPUT_FIELDS | VARIANT_INPUT_FIELDS | {
    "options", "variants", "images", "metafields", "collections",
}
_HIGH_RISK_FIELDS = {"handle", "status", "options", "variants", "images"}


def _validate_fields(fields: List[str]) -> List[str]:
    selected = list(dict.fromkeys(fields or []))
    unknown = [field for field in selected if field not in TRANSFER_FIELDS]
    if not selected:
        raise ValueError("Select at least one product field to transfer")
    if unknown:
        raise ValueError(f"Unsupported transfer field(s): {', '.join(unknown)}")
    if "variants" in selected:
        selected.extend(field for field in VARIANT_INPUT_FIELDS if field not in selected)
    return selected


def _variant_key(variant: Dict[str, Any]) -> tuple:
    options = tuple(variant.get(f"option{i}") for i in (1, 2, 3))
    return options


def _variant_payload(variant: Dict[str, Any], fields: List[str], create: bool) -> Dict[str, Any]:
    payload = {
        field: variant.get(field) for field in fields
        if field in VARIANT_INPUT_FIELDS and field in variant
    }
    for option in ("option1", "option2", "option3"):
        if create and variant.get(option) is not None:
            payload[option] = variant[option]
    return payload


def _create_payload(product: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
    payload = {"title": product.get("title"), "handle": product.get("handle")}
    for field in PRODUCT_INPUT_FIELDS:
        if field in fields and field in product:
            payload[field] = product[field]
    variant_fields = [field for field in fields if field in VARIANT_INPUT_FIELDS]
    if "options" in fields or variant_fields:
        payload["options"] = [
            {key: value for key, value in option.items() if key in ("name", "position", "values")}
            for option in product.get("options") or []
        ]
    if variant_fields:
        payload["variants"] = [
            _variant_payload(variant, fields, create=True)
            for variant in product.get("variants") or []
        ]
    if "images" in fields:
        payload["images"] = [
            {key: value for key, value in image.items() if key in ("src", "alt", "position")}
            for image in product.get("images") or []
        ]
    return payload


def build_transfer_preview(
    source_snapshot: Dict[str, Any],
    destination_snapshot: Dict[str, Any],
    handle: str,
    fields: List[str],
    create_if_missing: bool = False,
    replace_images: bool = False,
) -> Dict[str, Any]:
    selected = _validate_fields(fields)
    source = (source_snapshot.get("products") or {}).get(handle)
    if not source:
        raise ValueError(f"Source product not found: {handle}")
    destination = (destination_snapshot.get("products") or {}).get(handle)
    action = "update" if destination else "create"
    source_details = product_details(source, source_snapshot)
    destination_details = product_details(destination, destination_snapshot) if destination else {}

    operations = []
    for field in selected:
        if field == "variants":
            continue
        if field in VARIANT_INPUT_FIELDS:
            source_value = [
                {"sku": variant.get("sku"), "title": variant.get("title"), "value": variant.get(field)}
                for variant in source.get("variants") or []
            ]
            destination_value = [
                {"sku": variant.get("sku"), "title": variant.get("title"), "value": variant.get(field)}
                for variant in (destination or {}).get("variants") or []
            ]
        elif field == "options":
            source_value = source.get("options") or []
            destination_value = (destination or {}).get("options") or []
        elif field == "images":
            source_value = source.get("images") or []
            destination_value = (destination or {}).get("images") or []
        else:
            source_value = source_details.get(field)
            destination_value = destination_details.get(field)
        operations.append({
            "field": field,
            "action": action,
            "source": source_value,
            "destination": destination_value,
            "risk": "HIGH" if field in _HIGH_RISK_FIELDS or (field == "images" and replace_images) else "MEDIUM",
        })

    warnings = []
    if action == "create":
        if not create_if_missing:
            warnings.append("Destination product is missing. Enable 'Create product if missing' before executing.")
        warnings.append("Title, handle, and required variant option structure are included when a product is created.")
    if "handle" in selected:
        warnings.append("Changing the handle changes the product's storefront URL.")
    if replace_images and "images" in selected:
        warnings.append("Destination images absent from the source product will be deleted.")
    if "inventory_quantity" in selected:
        warnings.append("Inventory quantities are location-specific and are not transferred.")
    if "collections" in selected:
        warnings.append("Smart-collection membership is rule-based; only custom collections are copied.")

    return {
        "action": action,
        "handle": handle,
        "source_product_id": source.get("id"),
        "destination_product_id": (destination or {}).get("id"),
        "fields": selected,
        "operations": operations,
        "warnings": warnings,
        "can_execute": action == "update" or create_if_missing,
    }


async def execute_transfer(
    source_url: str,
    source_token: str,
    destination_url: str,
    destination_token: str,
    source_snapshot: Dict[str, Any],
    destination_snapshot: Dict[str, Any],
    handle: str,
    fields: List[str],
    create_if_missing: bool = False,
    replace_images: bool = False,
) -> Dict[str, Any]:
    selected = _validate_fields(fields)
    source_cached = (source_snapshot.get("products") or {}).get(handle)
    if not source_cached:
        raise ValueError(f"Source product not found: {handle}")
    destination_cached = (destination_snapshot.get("products") or {}).get(handle)
    if not destination_cached and not create_if_missing:
        raise ValueError("Destination product is missing and creation was not confirmed")

    result: Dict[str, Any] = {
        "status": "ok",
        "action": "update" if destination_cached else "create",
        "handle": handle,
        "operations": [],
        "warnings": [],
        "product": None,
    }

    def record(field: str, status: str = "ok", error: Optional[str] = None):
        result["operations"].append({"field": field, "status": status, "error": error})
        if status == "error":
            result["status"] = "error"

    async with ShopifyClient(source_url, source_token) as source_client, ShopifyClient(destination_url, destination_token) as destination_client:
        source = await source_client.get_product(source_cached["id"])
        destination = await destination_client.find_product_by_handle(handle)
        action = "update" if destination else "create"
        result["action"] = action

        if action == "create":
            try:
                destination = await destination_client.create_product(_create_payload(source, selected))
                for field in selected:
                    record(field)
            except Exception as exc:
                record("product", "error", str(exc))
                return result

        product_id = destination["id"]
        result["destination_product_id"] = product_id

        if action == "update":
            scalar_fields = [field for field in PRODUCT_INPUT_FIELDS if field in selected]
            if scalar_fields:
                try:
                    payload = {field: source.get(field) for field in scalar_fields if field in source}
                    destination = await destination_client.update_product(product_id, payload)
                    for field in scalar_fields:
                        record(field)
                except Exception as exc:
                    for field in scalar_fields:
                        record(field, "error", str(exc))

            variant_fields = [field for field in selected if field in VARIANT_INPUT_FIELDS]
            if variant_fields:
                try:
                    destination_variants = [dict(variant) for variant in destination.get("variants") or []]
                    changed = False
                    for source_variant in source.get("variants") or []:
                        match = None
                        source_sku = (source_variant.get("sku") or "").strip()
                        if source_sku:
                            match = next((v for v in destination_variants if (v.get("sku") or "").strip() == source_sku), None)
                        if match is None:
                            match = next((v for v in destination_variants if _variant_key(v) == _variant_key(source_variant)), None)
                        if match:
                            match.update(_variant_payload(source_variant, variant_fields, create=False))
                            changed = True
                            record(f"variant:{source_sku or source_variant.get('title')}")
                        elif "variants" in selected:
                            new_variant = _variant_payload(source_variant, selected, create=True)
                            destination_variants.append(new_variant)
                            changed = True
                            record(f"variant:{source_sku or source_variant.get('title')}:create")
                        else:
                            result["warnings"].append(
                                f"No matching destination variant for {source_sku or source_variant.get('title')}; skipped."
                            )
                    if changed:
                        destination = await destination_client.update_product(product_id, {"variants": destination_variants})
                except Exception as exc:
                    record("variants", "error", str(exc))

            if "options" in selected:
                try:
                    options = [
                        {key: value for key, value in option.items() if key in ("name", "position", "values")}
                        for option in source.get("options") or []
                    ]
                    destination = await destination_client.update_product(product_id, {"options": options})
                    record("options")
                except Exception as exc:
                    record("options", "error", str(exc))

            if "images" in selected:
                source_images = source.get("images") or []
                destination_images = destination.get("images") or []
                existing_urls = {image.get("src") for image in destination_images}
                additions = [
                    {key: value for key, value in image.items() if key in ("src", "alt", "position")}
                    for image in source_images if image.get("src") not in existing_urls
                ]
                try:
                    if additions:
                        destination = await destination_client.update_product(product_id, {"images": additions})
                    record("images:add")
                    if replace_images:
                        source_urls = {image.get("src") for image in source_images}
                        for image in destination_images:
                            if image.get("src") not in source_urls:
                                await destination_client._delete(f"/products/{product_id}/images/{image['id']}.json")
                        record("images:replace")
                except Exception as exc:
                    record("images", "error", str(exc))

        if "metafields" in selected:
            try:
                metafields = await source_client.get_product_metafields(source["id"])
                for field in metafields:
                    await destination_client.set_product_metafield(
                        product_id,
                        namespace=field["namespace"],
                        key=field["key"],
                        value=field.get("value"),
                        value_type=field.get("type") or "string",
                    )
                record("metafields")
            except Exception as exc:
                record("metafields", "error", str(exc))

        if "collections" in selected:
            source_details = product_details(source, source_snapshot)
            source_collections = {
                (_lookup_collection(source_snapshot, title) or {}).get("_type"): title
                for title in source_details["collections"]
            }
            for collection_type, title in source_collections.items():
                if collection_type == "smart":
                    result["warnings"].append(f"Smart collection '{title}' is rule-based and was not copied.")
                    continue
                try:
                    collection = await destination_client.find_custom_collection_by_title(title)
                    if not collection:
                        collection = await destination_client.create_custom_collection(title)
                    memberships = await destination_client.get_collects(collection["id"])
                    if not any(item.get("product_id") == product_id for item in memberships):
                        await destination_client.add_to_collection(collection["id"], product_id)
                    record(f"collection:{title}")
                except Exception as exc:
                    record(f"collection:{title}", "error", str(exc))

        result["product"] = await destination_client.get_product(product_id)
    return result


def _lookup_collection(snapshot: Dict[str, Any], title: str) -> Optional[Dict[str, Any]]:
    return next(
        (collection for collection in (snapshot.get("collections") or {}).values()
         if (collection.get("title") or "").casefold() == title.casefold()),
        None,
    )
