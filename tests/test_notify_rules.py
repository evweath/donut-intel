"""Tests for scheduled-search notification matching (backend/notify/rules.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.notify import rules


def test_flatten_beat_price_includes_flat_and_grouped():
    result = {
        "results": [{"title": "A", "price": 25.0, "fuzzy_score": 90, "domain": "a.com", "url": "u"}],
        "groups": [{"our_price": 30, "results": [
            {"title": "B", "price": "$19.99", "fuzzy_score": 81, "domain": "b.com", "url": "u2"}]}],
    }
    rows = rules.flatten_results("beat_price", result)
    assert len(rows) == 2
    assert {r["title"] for r in rows} == {"A", "B"}
    # string price parsed to float
    b = next(r for r in rows if r["title"] == "B")
    assert b["price"] == 19.99 and b["match"] == 81


def test_flatten_find_product_includes_web_and_competitor():
    result = {
        "results": [{"title": "web1", "price": "$10.00", "domain": "w.com"}],
        "competitor_results": [{"title": "c1", "price": 12.0, "fuzzy_score": 70, "domain": "c.com"}],
    }
    rows = rules.flatten_results("find_product", result)
    assert len(rows) == 2
    web = next(r for r in rows if r["title"] == "web1")
    assert web["price"] == 10.0 and web["match"] is None  # web results have no score


def test_evaluate_price_and_match_rule():
    rows = [
        {"title": "cheap+high", "price": 25.0, "match": 85, "domain": "x", "url": "x"},
        {"title": "cheap+low", "price": 20.0, "match": 50, "domain": "x", "url": "x"},
        {"title": "pricey+high", "price": 40.0, "match": 95, "domain": "x", "url": "x"},
        {"title": "no-price", "price": None, "match": 99, "domain": "x", "url": "x"},
    ]
    rule = {"max_price": 27, "min_match": 80}
    matched = rules.evaluate(rows, rule)
    assert [r["title"] for r in matched] == ["cheap+high"]


def test_evaluate_unknown_values_excluded_when_thresholds_set():
    rows = [{"title": "no-match", "price": 5.0, "match": None, "domain": "x", "url": "x"}]
    assert rules.evaluate(rows, {"min_match": 80}) == []
    assert rules.evaluate(rows, {"max_price": 10}) == rows  # price known, no match rule


def test_format_email_lists_matches():
    matched = [{"title": "50lb Sugar", "price": 24.5, "match": 88, "domain": "supplier.com", "url": "http://x"}]
    subject, body = rules.format_email("Sugar watch", "50 pound bags of sugar", matched,
                                       {"max_price": 27, "min_match": 80})
    assert "1 matching result" in subject
    assert "50lb Sugar" in body and "$24.50" in body and "88%" in body
    assert "price ≤ $27" in body and "match ≥ 80%" in body
