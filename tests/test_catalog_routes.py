import pytest
from fastapi import HTTPException

from backend.api.catalog_routes import _load_available_snapshots, _load_snapshots
from backend.shopify import scan_cache


def _fake_snapshots(monkeypatch):
    monkeypatch.setattr(
        scan_cache,
        "load_snapshot",
        lambda domain, max_age_days: {"products": {}, "menus": []} if domain == "ok.example" else None,
    )


def test_available_snapshots_do_not_block_on_failed_store(monkeypatch):
    _fake_snapshots(monkeypatch)
    snapshots, unavailable = _load_available_snapshots(["ok.example", "failed.example"])
    assert set(snapshots) == {"ok.example"}
    assert unavailable == ["failed.example"]


def test_transfer_snapshot_loading_still_requires_both_stores(monkeypatch):
    _fake_snapshots(monkeypatch)
    with pytest.raises(HTTPException) as error:
        _load_snapshots(["ok.example", "failed.example"])
    assert error.value.status_code == 409
    assert "failed.example" in error.value.detail
