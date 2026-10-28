import pytest

from backend.shopify.catalog import scan_store
from backend.shopify.client import ShopifyClient


@pytest.mark.asyncio
async def test_scan_store_reads_active_draft_and_archived_products():
    class Client:
        def __init__(self):
            self.statuses = []

        async def get_shop(self):
            return {"name": "Test shop"}

        async def iter_products(self, status):
            self.statuses.append(status)
            product_id = {"active": 1, "draft": 2, "archived": 3}[status]
            yield {"id": product_id, "title": status, "handle": status, "variants": []}

        async def get_custom_collections(self):
            return []

        async def get_smart_collections(self):
            return []

        async def get_collects(self):
            return []

        async def get_all_product_metafields(self):
            return []

    client = Client()
    snapshot = await scan_store(client)
    assert client.statuses == ["active", "draft", "archived"]
    assert set(snapshot["products"]) == {"active", "draft", "archived"}


@pytest.mark.asyncio
async def test_find_product_by_handle_checks_every_status():
    class Response:
        def __init__(self, products):
            self.products = products

        def json(self):
            return {"products": self.products}

    class Client:
        def __init__(self):
            self.statuses = []

        async def _get(self, path, params=None):
            self.statuses.append(params["status"])
            if params["status"] == "archived":
                return Response([{"id": 3, "handle": "alpha"}])
            return Response([])

    client = Client()
    product = await ShopifyClient.find_product_by_handle(client, "alpha")
    assert product["id"] == 3
    assert client.statuses == ["active", "draft", "archived"]
