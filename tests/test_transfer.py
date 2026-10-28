import pytest

from backend.shopify.transfer import (
    _create_payload,
    build_transfer_preview,
    execute_transfer,
)


def _product(product_id=1, title="Alpha", price="10.00"):
    return {
        "id": product_id,
        "title": title,
        "handle": "alpha",
        "body_html": "<p>Description</p>",
        "vendor": "Vendor",
        "product_type": "Equipment",
        "status": "active",
        "tags": "one, two",
        "options": [{"id": 11, "name": "Size", "position": 1, "values": ["Small"]}],
        "variants": [{
            "id": 21 if product_id == 1 else 22,
            "product_id": product_id,
            "title": "Small",
            "sku": "A-S",
            "price": price,
            "option1": "Small",
        }],
        "images": [{"id": 41, "src": "https://img.example/a.jpg", "alt": "Alpha"}],
    }


def _snapshot(product):
    return {
        "products": {"alpha": product},
        "products_by_id": {product["id"]: "alpha"},
        "collections": {},
        "product_collections": {},
        "collection_products": {},
        "metafields": {},
    }


def test_preview_is_per_product_and_per_field():
    preview = build_transfer_preview(
        _snapshot(_product()),
        _snapshot(_product(product_id=2, title="Old title", price="12.00")),
        "alpha",
        ["title", "price"],
    )
    assert preview["action"] == "update"
    assert preview["source_product_id"] == 1
    assert preview["destination_product_id"] == 2
    assert preview["fields"] == ["title", "price"]
    assert preview["can_execute"] is True


def test_preview_requires_confirmation_before_creating():
    preview = build_transfer_preview(_snapshot(_product()), {"products": {}}, "alpha", ["title"])
    assert preview["action"] == "create"
    assert preview["can_execute"] is False
    confirmed = build_transfer_preview(
        _snapshot(_product()), {"products": {}}, "alpha", ["title"], create_if_missing=True,
    )
    assert confirmed["can_execute"] is True


def test_create_payload_strips_ids_and_keeps_required_variant_structure():
    payload = _create_payload(_product(), ["title", "price", "images"])
    assert payload["title"] == "Alpha"
    assert payload["handle"] == "alpha"
    assert payload["options"][0] == {"name": "Size", "position": 1, "values": ["Small"]}
    assert payload["variants"] == [{"price": "10.00", "option1": "Small"}]
    assert payload["images"] == [{"src": "https://img.example/a.jpg", "alt": "Alpha"}]


class FakeClient:
    instances = {}

    def __init__(self, url, token):
        self.url = url
        self.updates = []
        self.metafields = []
        self.product = _product(product_id=2, title="Old title", price="12.00")
        if url == "https://source.example":
            self.product = _product()
        self.__class__.instances[url] = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get_product(self, product_id):
        return self.product

    async def find_product_by_handle(self, handle):
        return self.product

    async def update_product(self, product_id, payload):
        self.updates.append(payload)
        self.product.update(payload)
        return self.product

    async def get_product_metafields(self, product_id):
        return [{"namespace": "custom", "key": "material", "type": "string", "value": "Steel"}]

    async def set_product_metafield(self, product_id, namespace, key, value, value_type):
        self.metafields.append((product_id, namespace, key, value, value_type))
        return {}


@pytest.mark.asyncio
async def test_execute_updates_only_selected_fields(monkeypatch):
    FakeClient.instances = {}
    monkeypatch.setattr("backend.shopify.transfer.ShopifyClient", FakeClient)

    result = await execute_transfer(
        "https://source.example", "source-token",
        "https://destination.example", "destination-token",
        _snapshot(_product()), _snapshot(_product(product_id=2)),
        "alpha", ["title", "price", "metafields"],
    )

    destination = FakeClient.instances["https://destination.example"]
    assert destination.updates[0] == {"title": "Alpha"}
    assert destination.updates[1] == {"variants": [{
        "id": 22, "product_id": 2, "title": "Small", "sku": "A-S",
        "price": "10.00", "option1": "Small",
    }]}
    assert destination.metafields == [(2, "custom", "material", "Steel", "string")]
    assert result["status"] == "ok"
    assert result["action"] == "update"
    assert "body_html" not in destination.updates[0]
