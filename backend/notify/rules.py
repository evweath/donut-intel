"""
Notification rule evaluation for scheduled searches.

A scheduled Beat-Price / Find-Product job may carry a `notify` rule. After the
search runs we flatten its results into a common shape and keep the rows that
satisfy the rule (e.g. price <= $27 AND match >= 80%). If any survive (and the
job has recipients) an alarm email is sent.

Kept free of scheduler / FastAPI imports so it can be unit-tested directly.
"""
import re
from typing import Any, Dict, List, Optional


def parse_price(val: Any) -> Optional[float]:
    """'$1,029.99' / 1029.99 / None -> float | None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    digits = re.sub(r"[^\d.]", "", str(val))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def flatten_results(job_type: str, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize a search response into rows: {title, url, domain, price, match}."""
    raw: List[Dict[str, Any]] = []
    if job_type == "beat_price":
        raw.extend(result.get("results") or [])
        for g in (result.get("groups") or []):
            raw.extend(g.get("results") or [])
    elif job_type == "find_product":
        raw.extend(result.get("results") or [])
        raw.extend(result.get("competitor_results") or [])
    else:
        raw.extend(result.get("results") or [])

    rows: List[Dict[str, Any]] = []
    for r in raw:
        score = r.get("fuzzy_score")
        rows.append({
            "title": r.get("title") or r.get("domain") or "(untitled)",
            "url": r.get("url"),
            "domain": r.get("domain"),
            "price": parse_price(r.get("price")),
            "match": int(score) if isinstance(score, (int, float)) else None,
        })
    return rows


def evaluate(rows: List[Dict[str, Any]], rule: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the rows that satisfy the rule.

    rule keys: max_price (<=), min_match (>=). A row with an unknown price is
    excluded when max_price is set; an unknown match is excluded when min_match
    is set — an alarm only fires on results we can actually qualify.
    """
    max_price = rule.get("max_price")
    min_match = rule.get("min_match")
    out = []
    for r in rows:
        if max_price is not None:
            if r["price"] is None or r["price"] > float(max_price):
                continue
        if min_match is not None:
            if r["match"] is None or r["match"] < float(min_match):
                continue
        out.append(r)
    return out


def rule_summary(rule: Dict[str, Any]) -> str:
    parts = []
    if rule.get("max_price") is not None:
        parts.append(f"price ≤ ${rule['max_price']}")
    if rule.get("min_match") is not None:
        parts.append(f"match ≥ {rule['min_match']}%")
    if rule.get("min_results"):
        parts.append(f"at least {rule['min_results']} result(s)")
    return ", ".join(parts) or "any result"


def format_email(job_name: str, search_label: str, matched: List[Dict[str, Any]],
                 rule: Dict[str, Any]) -> tuple:
    """Build (subject, text_body) for a notification email."""
    subject = f"[Donut Intel] {job_name}: {len(matched)} matching result(s)"
    lines = [
        f"Scheduled search \"{job_name}\" found {len(matched)} result(s) matching your alert.",
        "",
        f"Search: {search_label}",
        f"Alert when: {rule_summary(rule)}",
        "",
        "Matching results:",
    ]
    for i, r in enumerate(matched, 1):
        price = f"${r['price']:.2f}" if r["price"] is not None else "n/a"
        match = f"{r['match']}%" if r["match"] is not None else "n/a"
        lines.append(f"  {i}. {r['title']}")
        lines.append(f"     price {price} | match {match} | {r.get('domain') or ''}")
        if r.get("url"):
            lines.append(f"     {r['url']}")
    lines.append("")
    lines.append("— Donut Intel scheduler")
    return subject, "\n".join(lines)
