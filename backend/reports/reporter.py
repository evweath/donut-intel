"""
Reports Module (F61-F63)
Generates HTML reports: price disparity, competitor intelligence, new products summary.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from backend.database.db import session_scope
from backend.database.models import (
    Competitor,
    CompetitorProductMatch,
    PriceHistory,
    Product,
    ScanSession,
)

logger = logging.getLogger(__name__)

_STYLE = """
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f9f9f9; color: #222; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px; }
h1 { color: #d35400; border-bottom: 3px solid #d35400; padding-bottom: 8px; }
h2 { color: #444; margin-top: 32px; }
table { width: 100%; border-collapse: collapse; background: white; box-shadow: 0 1px 4px rgba(0,0,0,.1); border-radius: 6px; overflow: hidden; }
th { background: #d35400; color: white; padding: 10px 14px; text-align: left; font-size: 13px; }
td { padding: 8px 14px; border-bottom: 1px solid #eee; font-size: 13px; }
tr:last-child td { border-bottom: none; }
tr:nth-child(even) td { background: #fff8f3; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }
.badge-red { background: #fee; color: #c0392b; }
.badge-green { background: #efe; color: #1e8449; }
.badge-orange { background: #fff3e0; color: #d35400; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin: 24px 0; }
.stat-card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.1); text-align: center; }
.stat-card .value { font-size: 2rem; font-weight: bold; color: #d35400; }
.stat-card .label { font-size: 12px; color: #888; margin-top: 4px; }
.meta { color: #888; font-size: 12px; margin-bottom: 24px; }
</style>
"""


def _html_wrapper(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title} — Donut Intel</title>{_STYLE}</head>
<body><div class="container">
<h1>🍩 Donut Intel Platform</h1>
{body}
</div></body></html>"""


# --------------------------------------------------------------------------
# F63: Price Disparity Report
# --------------------------------------------------------------------------

def price_disparity_report(threshold_pct: float = 5.0) -> str:
    """
    List all products where any competitor price is lower than our source price
    by more than threshold_pct%.
    """
    rows = []

    with session_scope() as db:
        matches = (
            db.query(CompetitorProductMatch)
            .filter(
                CompetitorProductMatch.is_active == True,
                CompetitorProductMatch.competitor_price > 0,
            )
            .all()
        )

        for m in matches:
            product = db.get(Product, m.master_product_id)
            if not product or not product.price_canonical:
                continue
            our_price = product.price_canonical
            their_price = m.competitor_price
            diff_pct = (our_price - their_price) / our_price * 100
            if diff_pct >= threshold_pct:
                comp = db.get(Competitor, m.competitor_id)
                rows.append({
                    "product": product.canonical_title,
                    "our_price": our_price,
                    "their_price": their_price,
                    "diff_pct": round(diff_pct, 1),
                    "competitor": comp.domain if comp else "?",
                    "url": m.competitor_url or "",
                    "scanned": m.scanned_at.strftime("%Y-%m-%d") if m.scanned_at else "",
                })

    rows.sort(key=lambda r: r["diff_pct"], reverse=True)

    table_rows = ""
    for r in rows:
        badge = f'<span class="badge badge-red">-{r["diff_pct"]}%</span>'
        link = f'<a href="{r["url"]}" target="_blank">{r["competitor"]}</a>' if r["url"] else r["competitor"]
        table_rows += f"""<tr>
            <td>{r["product"]}</td>
            <td>${r["our_price"]:.2f}</td>
            <td>${r["their_price"]:.2f}</td>
            <td>{badge}</td>
            <td>{link}</td>
            <td>{r["scanned"]}</td>
        </tr>"""

    body = f"""
<h2>Price Disparity Report</h2>
<p class="meta">Products where competitors charge more than {threshold_pct}% less than our source price.
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | {len(rows)} products flagged</p>
<table>
  <thead><tr><th>Product</th><th>Our Price</th><th>Competitor Price</th><th>Difference</th><th>Competitor</th><th>Last Scanned</th></tr></thead>
  <tbody>{table_rows if table_rows else '<tr><td colspan="6" style="text-align:center;color:#888">No disparity found</td></tr>'}</tbody>
</table>"""
    return _html_wrapper("Price Disparity Report", body)


# --------------------------------------------------------------------------
# F62: Competitor Intelligence Report
# --------------------------------------------------------------------------

def competitor_report(competitor_id: int) -> str:
    with session_scope() as db:
        comp = db.get(Competitor, competitor_id)
        if not comp:
            return _html_wrapper("Error", "<p>Competitor not found.</p>")

        matches = (
            db.query(CompetitorProductMatch)
            .filter(
                CompetitorProductMatch.competitor_id == competitor_id,
                CompetitorProductMatch.is_active == True,
            )
            .order_by(CompetitorProductMatch.competitor_price)
            .all()
        )

        # Summary stats
        total = len(matches)
        prices = [m.competitor_price for m in matches if m.competitor_price]
        avg_price = sum(prices) / len(prices) if prices else 0
        in_stock = sum(1 for m in matches if m.in_stock)

        stat_grid = f"""<div class="stat-grid">
  <div class="stat-card"><div class="value">{total}</div><div class="label">Matched Products</div></div>
  <div class="stat-card"><div class="value">{in_stock}</div><div class="label">In Stock</div></div>
  <div class="stat-card"><div class="value">${avg_price:.2f}</div><div class="label">Avg Price</div></div>
  <div class="stat-card"><div class="value">{comp.last_scanned_at.strftime('%Y-%m-%d') if comp.last_scanned_at else 'Never'}</div><div class="label">Last Scanned</div></div>
</div>"""

        table_rows = ""
        for m in matches:
            product = db.get(Product, m.master_product_id)
            our_price = product.price_canonical if product else None
            diff = ""
            badge = ""
            if our_price and m.competitor_price:
                diff_val = m.competitor_price - our_price
                diff_pct = diff_val / our_price * 100
                color = "badge-green" if diff_val > 0 else "badge-red"
                sign = "+" if diff_val > 0 else ""
                badge = f'<span class="badge {color}">{sign}{diff_pct:.1f}%</span>'
                diff = f"${diff_val:+.2f}"

            # Price history count
            ph_count = len(m.price_history)

            link = f'<a href="{m.competitor_url}" target="_blank" style="color:#d35400">{m.competitor_title or "View"}</a>' if m.competitor_url else (m.competitor_title or "")
            table_rows += f"""<tr>
                <td>{product.canonical_title if product else '?'}</td>
                <td>{link}</td>
                <td>${m.competitor_price:.2f if m.competitor_price else 'N/A'}</td>
                <td>${our_price:.2f if our_price else 'N/A'}</td>
                <td>{diff} {badge}</td>
                <td>{'Yes' if m.in_stock else 'No'}</td>
                <td>{m.match_type or ''}</td>
                <td>{ph_count} records</td>
                <td>{m.scanned_at.strftime('%Y-%m-%d') if m.scanned_at else ''}</td>
            </tr>"""

        first_scanned = comp.first_scanned_at.strftime("%Y-%m-%d") if comp.first_scanned_at else "Never"
        last_scanned = comp.last_scanned_at.strftime("%Y-%m-%d") if comp.last_scanned_at else "Never"

        body = f"""
<h2>Competitor Intelligence: {comp.domain}</h2>
<p class="meta">First scanned: {first_scanned} | Last scanned: {last_scanned} | Session: {comp.scan_session_name or 'N/A'}</p>
{stat_grid}
<table>
  <thead><tr><th>Our Product</th><th>Their Listing</th><th>Their Price</th><th>Our Price</th><th>Diff</th><th>In Stock</th><th>Match Type</th><th>History</th><th>Scanned</th></tr></thead>
  <tbody>{table_rows if table_rows else '<tr><td colspan="9" style="text-align:center;color:#888">No matches found</td></tr>'}</tbody>
</table>"""
        return _html_wrapper(f"Competitor Report: {comp.domain}", body)


# --------------------------------------------------------------------------
# F61: New Products / Summary Report
# --------------------------------------------------------------------------

def summary_report(days: int = 7) -> str:
    since = datetime.utcnow() - timedelta(days=days)

    with session_scope() as db:
        new_products = (
            db.query(Product)
            .filter(Product.is_active == True, Product.created_at >= since)
            .order_by(Product.created_at.desc())
            .all()
        )

        # Price changes (products with recent price history)
        price_changes = (
            db.query(PriceHistory)
            .filter(PriceHistory.recorded_at >= since)
            .order_by(PriceHistory.recorded_at.desc())
            .limit(50)
            .all()
        )

        # New competitors
        new_competitors = (
            db.query(Competitor)
            .filter(Competitor.added_at >= since)
            .order_by(Competitor.added_at.desc())
            .all()
        )

        # Scan summary
        scans = (
            db.query(ScanSession)
            .filter(ScanSession.started_at >= since, ScanSession.status == "completed")
            .all()
        )
        total_scanned = sum(s.total_scraped or 0 for s in scans)
        total_new = sum(s.new_products or 0 for s in scans)

        stat_grid = f"""<div class="stat-grid">
  <div class="stat-card"><div class="value">{len(new_products)}</div><div class="label">New Products</div></div>
  <div class="stat-card"><div class="value">{len(price_changes)}</div><div class="label">Price Changes</div></div>
  <div class="stat-card"><div class="value">{len(new_competitors)}</div><div class="label">New Competitors</div></div>
  <div class="stat-card"><div class="value">{len(scans)}</div><div class="label">Scans Completed</div></div>
</div>"""

        # New products table
        np_rows = "".join(f"""<tr>
            <td>{p.id}</td><td>{p.canonical_title}</td><td>{p.manufacturer or ''}</td>
            <td>${p.price_canonical:.2f if p.price_canonical else 'N/A'}</td>
            <td>{p.category or ''}</td>
            <td>{p.created_at.strftime('%Y-%m-%d') if p.created_at else ''}</td>
        </tr>""" for p in new_products)

        # Competitor listing
        comp_rows = "".join(f"""<tr>
            <td>{c.domain}</td><td>{c.name or ''}</td>
            <td>{c.added_at.strftime('%Y-%m-%d') if c.added_at else ''}</td>
        </tr>""" for c in new_competitors)

        body = f"""
<h2>Platform Summary — Last {days} Days</h2>
<p class="meta">Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Scans: {len(scans)} completed, {total_scanned} pages scraped, {total_new} new products</p>
{stat_grid}

<h2>New Products ({len(new_products)})</h2>
<table>
  <thead><tr><th>ID</th><th>Title</th><th>Manufacturer</th><th>Price</th><th>Category</th><th>Added</th></tr></thead>
  <tbody>{np_rows if np_rows else '<tr><td colspan="6" style="text-align:center;color:#888">None</td></tr>'}</tbody>
</table>

<h2>New Competitors ({len(new_competitors)})</h2>
<table>
  <thead><tr><th>Domain</th><th>Name</th><th>Discovered</th></tr></thead>
  <tbody>{comp_rows if comp_rows else '<tr><td colspan="3" style="text-align:center;color:#888">None</td></tr>'}</tbody>
</table>"""
        return _html_wrapper(f"Platform Summary — Last {days} Days", body)


# --------------------------------------------------------------------------
# F22: Price Comparison for a single product
# --------------------------------------------------------------------------

def price_comparison_report(product_id: int) -> str:
    with session_scope() as db:
        product = db.get(Product, product_id)
        if not product:
            return _html_wrapper("Error", "<p>Product not found.</p>")

        matches = (
            db.query(CompetitorProductMatch)
            .filter(
                CompetitorProductMatch.master_product_id == product_id,
                CompetitorProductMatch.is_active == True,
                CompetitorProductMatch.competitor_price > 0,
            )
            .order_by(CompetitorProductMatch.competitor_price)
            .all()
        )

        all_prices = []
        # Include our own source prices
        for source in product.sources:
            if source.is_active and source.source_price:
                all_prices.append({
                    "site": source.source_site,
                    "price": source.source_price,
                    "url": source.source_url,
                    "type": "source",
                    "scanned": source.scraped_at,
                })

        for m in matches:
            comp = db.get(Competitor, m.competitor_id)
            all_prices.append({
                "site": comp.domain if comp else "?",
                "price": m.competitor_price,
                "url": m.competitor_url or "",
                "type": "competitor",
                "scanned": m.scanned_at,
            })

        all_prices.sort(key=lambda x: x["price"])

        if all_prices:
            min_price = all_prices[0]["price"]
            max_price = all_prices[-1]["price"]
            prices_only = [p["price"] for p in all_prices]
            median_price = sorted(prices_only)[len(prices_only) // 2]
        else:
            min_price = max_price = median_price = 0

        stat_grid = f"""<div class="stat-grid">
  <div class="stat-card"><div class="value">${min_price:.2f}</div><div class="label">Lowest Price</div></div>
  <div class="stat-card"><div class="value">${max_price:.2f}</div><div class="label">Highest Price</div></div>
  <div class="stat-card"><div class="value">${median_price:.2f}</div><div class="label">Median Price</div></div>
  <div class="stat-card"><div class="value">{len(all_prices)}</div><div class="label">Listings Found</div></div>
</div>"""

        table_rows = ""
        for rank, p in enumerate(all_prices, 1):
            badge = '<span class="badge badge-green">LOWEST</span>' if rank == 1 else (
                '<span class="badge badge-red">HIGHEST</span>' if rank == len(all_prices) else "")
            type_badge = '<span class="badge badge-orange">OUR SITE</span>' if p["type"] == "source" else ""
            link = f'<a href="{p["url"]}" target="_blank" style="color:#d35400">{p["site"]}</a>' if p["url"] else p["site"]
            scanned = p["scanned"].strftime("%Y-%m-%d") if p["scanned"] else ""
            table_rows += f"""<tr>
                <td>#{rank}</td>
                <td>{link} {type_badge}</td>
                <td>${p["price"]:.2f} {badge}</td>
                <td>{scanned}</td>
            </tr>"""

        body = f"""
<h2>Price Comparison: {product.canonical_title}</h2>
<p class="meta">Manufacturer: {product.manufacturer or 'N/A'} | Model: {product.model_number or 'N/A'} | Our Price: ${product.price_canonical:.2f if product.price_canonical else 'N/A'}</p>
{stat_grid}
<table>
  <thead><tr><th>Rank</th><th>Website</th><th>Price</th><th>Last Checked</th></tr></thead>
  <tbody>{table_rows if table_rows else '<tr><td colspan="4" style="text-align:center;color:#888">No competitor prices found yet</td></tr>'}</tbody>
</table>"""
        return _html_wrapper(f"Price Comparison: {product.canonical_title}", body)
