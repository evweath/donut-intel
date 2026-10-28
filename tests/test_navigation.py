import pytest

from backend.shopify.navigation import analyze_menus, compare_menus, scan_menus


def _snapshot():
    return {
        "products": {
            "alpha": {"id": 1, "title": "Alpha", "handle": "alpha"},
            "beta": {"id": 2, "title": "Beta", "handle": "beta"},
            "gamma": {"id": 3, "title": "Gamma", "handle": "gamma"},
        },
        "products_by_id": {1: "alpha", 2: "beta", 3: "gamma"},
        "collections": {
            10: {"id": 10, "title": "Featured", "handle": "featured"},
        },
        "product_collections": {2: [10]},
        "collection_products": {10: [2]},
        "metafields": {},
    }


def test_menu_audit_finds_duplicates_and_missing_products():
    menus = [{
        "id": "menu-1",
        "handle": "main-menu",
        "title": "Main menu",
        "items": [
            {"id": "a", "title": "Alpha", "type": "PRODUCT", "url": "/products/alpha", "items": []},
            {"id": "b", "title": "Featured", "type": "COLLECTION", "url": "/collections/featured", "resourceId": "gid://shopify/Collection/10", "items": []},
            {"id": "c", "title": "More", "type": "HTTP", "url": "", "items": [
                {"id": "d", "title": "Alpha again", "type": "PRODUCT", "url": "https://shop.example/products/alpha", "items": []},
            ]},
        ],
    }]

    result = analyze_menus(menus, _snapshot())

    assert [p["handle"] for p in result["missing_products"]] == ["gamma"]
    assert result["counts"]["represented_products"] == 2
    assert result["duplicate_products"][0]["handle"] == "alpha"
    assert result["duplicate_products"][0]["count"] == 2
    assert result["duplicate_products"][0]["occurrences"][1]["path"] == "More › Alpha again"


def test_menu_audit_reports_unresolved_product_links():
    menus = [{"handle": "main", "title": "Main", "items": [
        {"id": "x", "title": "Gone", "type": "PRODUCT", "url": "/products/gone", "items": []},
    ]}]
    result = analyze_menus(menus, _snapshot())
    assert result["counts"]["unresolved_product_items"] == 1
    assert result["unresolved_product_items"][0]["product_handle"] == "gone"


def test_menu_comparison_reports_missing_and_changed_items():
    a = [{"handle": "main", "title": "Main", "items": [
        {"id": "a", "title": "Alpha", "type": "PRODUCT", "url": "/products/alpha", "items": []},
    ]}]
    b = [{"handle": "main", "title": "Main", "items": [
        {"id": "b", "title": "Alpha", "type": "PRODUCT", "url": "/products/other", "items": []},
    ]}]
    result = compare_menus({"a.example": a, "b.example": b})
    assert result["difference_count"] == 1
    assert result["items"][0]["different"] is True
    assert result["items"][0]["stores"]["b.example"]["url"] == "/products/other"


@pytest.mark.asyncio
async def test_scan_menus_follows_pagination():
    class Client:
        async def graphql(self, query, variables):
            if variables["cursor"] is None:
                return {"menus": {"nodes": [{"handle": "main", "items": []}],
                                  "pageInfo": {"hasNextPage": True, "endCursor": "next"}}}
            return {"menus": {"nodes": [{"handle": "footer", "items": []}],
                              "pageInfo": {"hasNextPage": False, "endCursor": None}}}

    menus = await scan_menus(Client())
    assert [menu["handle"] for menu in menus] == ["main", "footer"]
