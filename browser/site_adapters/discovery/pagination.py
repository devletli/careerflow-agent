"""Shared pagination + polite HTTP helpers for discovery connectors.

Only pagination, ordering and limit handling live here — no scoring,
no application logic.
"""

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

# 429 / 5xx give the source room to recover; anti-bot measures are never bypassed.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def fetch_with_backoff(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    **kwargs: Any,
) -> httpx.Response:
    """GET/POST with bounded exponential backoff on 429/5xx + network errors."""
    delay = base_delay
    for attempt in range(max_retries + 1):
        try:
            if method.upper() == "POST":
                res = await client.post(url, **kwargs)
            else:
                res = await client.get(url, **kwargs)
        except Exception as exc:
            if attempt >= max_retries:
                raise
            logger.debug("HTTP %s %s failed (%s); retry %d in %.1fs", method, url, exc, attempt + 1, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)
            continue
        if res.status_code not in RETRYABLE_STATUS or attempt >= max_retries:
            return res
        logger.debug("HTTP %s %s -> %s; retry %d in %.1fs", method, url, res.status_code, attempt + 1, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)
    raise RuntimeError("unreachable")  # pragma: no cover


async def paginate(
    fetch_page: Callable[[int], Awaitable[list[dict]]],
    *,
    max_items: int,
    max_pages: int,
    delay: float,
    deadline: float,
    start_page: int = 1,
) -> AsyncIterator[dict]:
    """Yields raw items page by page until exhausted, capped or out of time."""
    seen = 0
    for page in range(start_page, start_page + max_pages):
        if time.monotonic() > deadline or seen >= max_items:
            return
        items = await fetch_page(page)  # caller applies 429/5xx backoff
        if not items:
            return  # source exhausted
        for it in items:
            if seen >= max_items:
                return
            seen += 1
            yield it
        await asyncio.sleep(delay)


def time_deadline(budget_seconds: Optional[float] = None) -> float:
    """Monotonic deadline for a discovery round (infinite when budget unset)."""
    if not budget_seconds or budget_seconds <= 0:
        return float("inf")
    return time.monotonic() + budget_seconds
