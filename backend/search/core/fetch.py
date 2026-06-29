"""
HTTP fetch plumbing for the search core.

`_curl_get` uses primp browser impersonation (curl-equivalent TLS fingerprinting)
but keeps the URL in-process so it is not visible in the process table. This is
the single fetch primitive every engine adapter and page module should use.
"""
import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


async def _run_sync(fn):
    return await asyncio.get_event_loop().run_in_executor(None, fn)


# Transient fetch failures are retried with short backoff. On this deployment the
# outbound network (VPN/egress) flaps intermittently, and without retries a single
# blip makes every search engine return [] — surfacing as a misleading "0 found".
_FETCH_RETRIES = 3
_FETCH_BACKOFF_BASE = 0.4  # seconds: 0.4, 0.8


async def _curl_get(url: str, extra_headers: Optional[List[str]] = None, timeout: int = 15,
                    retries: int = _FETCH_RETRIES) -> str:
    """Fetch a URL via primp browser impersonation — same TLS fingerprinting as curl, but URL stays
    in-process memory and is not visible in the process table (ps/top).

    Retries transient connection failures a few times before giving up (returns '').
    HTTP error *statuses* return their body normally — only thrown exceptions retry.

    ``retries`` caps the number of attempts. The default (3) suits the main search
    engines, where an egress blip otherwise yields a misleading "0 found". Callers
    that probe many URLs and can tolerate a miss (e.g. competitor-site pattern
    probing across hundreds of domains) should pass ``retries=1`` to avoid paying
    3× the latency on every dead/timing-out URL.
    """
    import primp
    headers = {
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.9',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    for h in (extra_headers or []):
        if ': ' in h:
            k, v = h.split(': ', 1)
            headers[k] = v
    retries = max(1, retries)
    last_exc: Optional[BaseException] = None
    for attempt in range(retries):
        try:
            async with primp.AsyncClient(impersonate='random', timeout=timeout) as client:
                r = await asyncio.wait_for(client.get(url, headers=headers), timeout + 2)
                return r.text
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < retries:
                await asyncio.sleep(_FETCH_BACKOFF_BASE * (2 ** attempt))
    logger.debug("primp_get failed for %s after %d attempts: %s", url, retries, last_exc)
    return ''


async def check_internet_reachable(timeout: int = 6) -> bool:
    """Quick probe to tell 'network down' apart from 'genuinely no results'.

    Tries a couple of high-availability hosts (the same engines search relies on);
    returns True if any responds at all. Used so the UI can show a 'couldn't reach
    the internet' banner instead of a misleading 'Done — 0 found' when egress is down.
    """
    import primp
    for url in ("https://www.bing.com", "https://duckduckgo.com"):
        try:
            async with primp.AsyncClient(impersonate='random', timeout=timeout) as client:
                r = await asyncio.wait_for(client.get(url), timeout + 2)
                if r.text:
                    return True
        except Exception:
            continue
    return False
