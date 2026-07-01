"""
In-memory log of external search activity (products + competitors).

Every external search funnels through ``multi_engine_search`` (see
``backend/search/core/rank.py``), so that function records one block here per
call: the % match the search is using, the exact search term, the websites
(engines) queried with that term, and the results returned. The competitor
matcher also appends the actual match confidence per recorded match.

This is a separate, focused ring buffer (the main log_tail buffer churns too
fast during a scan) so the "Live Search Log" panel shown at the top of every
search page always reflects recent activity. Best-effort: recording never
raises into the search path.
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import List

_MAX_ENTRIES = 400
# Each entry is a single (possibly multi-line) block so one search's lines stay
# together even when many searches run concurrently.
_BUFFER: "deque[str]" = deque(maxlen=_MAX_ENTRIES)
_std_logger = logging.getLogger("backend.search.activity")

# Human-readable names for engine keys used by multi_engine_search.
_ENGINE_NAMES = {
    "ddg": "DuckDuckGo",
    "bing": "Bing",
    "google": "Google",
    "yahoo": "Yahoo",
    "shopping": "Google Shopping",
    "bing_shopping": "Bing Shopping",
    "yahoo_shopping": "Yahoo Shopping",
    "ddg_shopping": "DuckDuckGo Shopping",
    "costco": "Costco",
    "samsclub": "Sam's Club",
    "ubereats": "Uber Eats",
}


def engine_names(engines) -> List[str]:
    return [_ENGINE_NAMES.get(e, e) for e in (engines or [])]


def record_search(term, engines, results, match_pct=None, label="") -> None:
    """Append one search block: % match, term, websites searched, results.

    ``results`` is the list of result dicts multi_engine_search returns
    (each has 'domain', optional 'title'/'price'). Never pass secrets.
    """
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        head = "🔎"
        if match_pct is not None:
            head += f" {round(match_pct)}% match"
        if label:
            head += f" · {label}"
        lines = [f"{ts} {head}"]
        lines.append(f'   term: "{term}"')

        sites = engine_names(engines) or ["all engines"]
        lines.append("   searched: " + ", ".join(sites))

        results = results or []
        if results:
            lines.append(f"   results ({len(results)}):")
            for r in results[:12]:
                dom = r.get("domain") or r.get("url") or "?"
                price = r.get("price")
                price_str = f"  {price}" if price else ""
                lines.append(f"      • {dom}{price_str}")
            if len(results) > 12:
                lines.append(f"      … +{len(results) - 12} more")
        else:
            lines.append("   results: none")

        _BUFFER.append("\n".join(lines))
        _std_logger.info("search: %r via %s → %d results", term, ",".join(sites), len(results))
    except Exception:  # never break a search because logging failed
        pass


def record_match(domain, confidence=None, product_title="") -> None:
    """Append a single confirmed-match line with its real match confidence."""
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        pct = f" {round(confidence)}%" if confidence is not None else ""
        tail = f" — {product_title[:48]}" if product_title else ""
        _BUFFER.append(f"{ts} ✓ match{pct}: {domain}{tail}")
    except Exception:
        pass


def record_note(message: str) -> None:
    """Append a freeform status line (e.g. rate-limit notice)."""
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        _BUFFER.append(f"{ts} … {message}")
    except Exception:
        pass


def get_entries(n: int = 200) -> List[str]:
    if n >= len(_BUFFER):
        return list(_BUFFER)
    return list(_BUFFER)[-n:]


def clear() -> None:
    _BUFFER.clear()
