"""
Dedicated in-memory log of Shopify store connection attempts.

The main app log buffer (backend/log_tail.py) holds the last ~200 lines of ALL
logging, so connection diagnostics get pushed out quickly during a scan. This
keeps a separate, focused ring buffer of only connection-related events so the
Settings → Shopify Connection Log panel always shows the recent attempts.

`record()` also forwards to the standard logger, so these lines still land in the
main log file / dashboard live log. Never pass secrets (tokens, client secrets)
to record() — only hosts, status codes, and messages.
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import List

_MAX_LINES = 200
_BUFFER: "deque[str]" = deque(maxlen=_MAX_LINES)
_std_logger = logging.getLogger("backend.shopify.connection")


def record(message: str, level: str = "info") -> None:
    """Append a timestamped connection event and mirror it to the standard logger."""
    ts = datetime.now().strftime("%H:%M:%S")
    _BUFFER.append(f"{ts}  {message}")
    getattr(_std_logger, level, _std_logger.info)("conn: %s", message)


def get_lines(n: int = 120) -> List[str]:
    if n >= len(_BUFFER):
        return list(_BUFFER)
    return list(_BUFFER)[-n:]


def clear() -> None:
    _BUFFER.clear()
