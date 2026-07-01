"""USA-domain filter + Beat-Price successful/potential split."""
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.search.core.parse import is_usa_domain, filter_usa_domains
from backend.search.engine import find_suppliers


def test_is_usa_domain_examples():
    keep = ["amazon.com", "walmart.com", "shop.us", "acme.net", "company.co", "x.io"]
    drop = ["acme.co.uk", "supplier.ca", "store.com.au", "x.de", "y.cn", "shop.fr"]
    assert all(is_usa_domain(d) for d in keep), [d for d in keep if not is_usa_domain(d)]
    assert all(not is_usa_domain(d) for d in drop), [d for d in drop if is_usa_domain(d)]


def test_filter_usa_domains_drops_foreign():
    rows = [{"domain": "a.com"}, {"domain": "b.co.uk"}, {"domain": "c.us"}, {"domain": "d.ca"}]
    kept = {r["domain"] for r in filter_usa_domains(rows)}
    assert kept == {"a.com", "c.us"}


async def _run_split(price_max=27, usa_only=True):
    desc = "Acme Widget Model X100"
    # title == description -> high fuzzy score for all
    rows = [
        {"url": "http://cheap.com/x", "domain": "cheap.com", "title": desc, "description": desc, "price": "$20.00", "source": "shopping"},
        {"url": "http://pricey.com/x", "domain": "pricey.com", "title": desc, "description": desc, "price": "$50.00", "source": "shopping"},
        {"url": "http://noprice.com/x", "domain": "noprice.com", "title": desc, "description": desc, "price": None, "source": "shopping"},
        {"url": "http://cheapuk.co.uk/x", "domain": "cheapuk.co.uk", "title": desc, "description": desc, "price": "$15.00", "source": "shopping"},
    ]

    async def fake_mes(query, max_results=10, engines=None, **kwargs):
        return rows

    async def passthrough(results, *a, **k):
        return results  # avoid live price-enrich fetches

    with patch("backend.search.pages.beat_price.multi_engine_search", side_effect=fake_mes), \
         patch("backend.search.pages.beat_price._google_shopping_search", new_callable=AsyncMock, return_value=[]), \
         patch("backend.search.pages.beat_price._image_search", new_callable=AsyncMock, return_value=[]), \
         patch("backend.search.pages.beat_price._enrich_prices", side_effect=passthrough):
        return await find_suppliers(description=desc, price_max=price_max, max_results=10, usa_only=usa_only)


@pytest.mark.asyncio
async def test_successful_vs_potential_split():
    successful, potential, _ = await _run_split(price_max=27, usa_only=True)
    succ = {r["domain"] for r in successful}
    pot = {r["domain"] for r in potential}
    # USA + price<=27 -> only cheap.com is successful
    assert succ == {"cheap.com"}
    # matched but price fails / unknown -> pricey ($50) and noprice (unknown)
    assert pot == {"pricey.com", "noprice.com"}
    # foreign .co.uk dropped from BOTH buckets
    assert "cheapuk.co.uk" not in succ and "cheapuk.co.uk" not in pot


@pytest.mark.asyncio
async def test_usa_only_off_keeps_foreign():
    successful, potential, _ = await _run_split(price_max=27, usa_only=False)
    all_domains = {r["domain"] for r in successful} | {r["domain"] for r in potential}
    assert "cheapuk.co.uk" in all_domains  # foreign cheap (<=27) now included
    # and it qualifies as successful (price $15 <= 27)
    assert "cheapuk.co.uk" in {r["domain"] for r in successful}


@pytest.mark.asyncio
async def test_no_price_limit_all_successful():
    successful, potential, _ = await _run_split(price_max=None, usa_only=True)
    # No price limit -> every USA fuzzy-passer is successful; none potential.
    assert {r["domain"] for r in successful} == {"cheap.com", "pricey.com", "noprice.com"}
    assert potential == []
