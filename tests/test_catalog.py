from backend.shopify.catalog import compare_catalogs, product_details


def _product(title="Alpha", price="10.00", tags="one, two"):
    return {
        "id": 1,
        "title": title,
        "handle": "alpha",
        "body_html": "<p>Description</p>",
        "vendor": "Vendor",
        "product_type": "Equipment",
        "status": "active",
        "tags": tags,
        "options": [{"id": 11, "name": "Size", "position": 1, "values": ["Small"]}],
        "variants": [{
            "id": 21,
            "product_id": 1,
            "inventory_item_id": 31,
            "title": "Small",
            "sku": "A-S",
            "price": price,
            "option1": "Small",
        }],
        "images": [{"id": 41, "product_id": 1, "src": "https://img.example/a.jpg", "alt": "Alpha"}],
    }


def _snapshot(product, collection_title="Featured"):
    return {
        "products": {"alpha": product},
        "products_by_id": {1: "alpha"},
        "collections": {10: {"id": 10, "title": collection_title, "handle": "featured"}},
        "product_collections": {1: [10]},
        "collection_products": {10: [1]},
        "metafields": {1: [{"namespace": "custom", "key": "material", "type": "string", "value": "Steel"}]},
    }


def test_product_details_normalizes_store_specific_ids():
    details = product_details(_product(), _snapshot(_product()))
    assert details["tags"] == ["one", "two"]
    assert "id" not in details["variants"][0]
    assert "inventory_item_id" not in details["variants"][0]
    assert "product_id" not in details["images"][0]
    assert details["collections"] == ["Featured"]
    assert details["metafields"][0]["value"] == "Steel"


def test_compare_catalogs_reports_field_differences_and_missing_stores():
    first = _snapshot(_product())
    second_product = _product(title="Alpha renamed", price="12.50", tags="two")
    second = _snapshot(second_product, collection_title="Sale")
    groups = compare_catalogs({"a.example": first, "b.example": second, "c.example": {"products": {}}})

    assert len(groups) == 1
    group = groups[0]
    assert group["missing"] == ["c.example"]
    assert {"title", "tags", "variants", "collections"}.issubset(group["difference_fields"])
    assert group["details"]["b.example"]["title"] == "Alpha renamed"
    assert group["details"]["a.example"]["variants"][0]["price"] == "10.00"


def test_compare_catalogs_can_hide_identical_products():
    snapshots = {"a.example": _snapshot(_product()), "b.example": _snapshot(_product())}
    assert compare_catalogs(snapshots, differences_only=True) == []
    assert len(compare_catalogs(snapshots, differences_only=False)) == 1


def test_compare_catalogs_searches_title_handle_and_sku():
    snapshots = {"a.example": _snapshot(_product()), "b.example": _snapshot(_product())}
    assert len(compare_catalogs(snapshots, search="A-S")) == 1
    assert compare_catalogs(snapshots, search="not-present") == []
