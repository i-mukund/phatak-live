"""Retry with exponential backoff and full jitter."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.core.errors import ProviderError, ProviderRateLimited
from app.core.logging import get_logger

T = TypeVar("T")
logger = get_logger(__name__)


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    label: str = "call",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run ``fn`` with retries.

    Non-retryable :class:`ProviderError` instances are re-raised immediately —
    retrying a 401 just burns quota. Rate-limit responses honour ``retry_after``.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except ProviderError as exc:
            last = exc
            if not exc.retryable or attempt == attempts:
                raise
            delay = _delay_for(exc, attempt, base_delay, max_delay)
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                label, attempt, attempts, exc, delay,
            )
            await sleep(delay)
        except (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError) as exc:
            last = exc
            if attempt == attempts:
                raise
            delay = _backoff(attempt, base_delay, max_delay)
            logger.warning(
                "%s transport error (attempt %d/%d): %s — retrying in %.2fs",
                label, attempt, attempts, exc, delay,
            )
            await sleep(delay)
    raise last  # type: ignore[misc]  # unreachable: loop always returns or raises


def _delay_for(exc: ProviderError, attempt: int, base: float, cap: float) -> float:
    if isinstance(exc, ProviderRateLimited) and exc.retry_after:
        return min(float(exc.retry_after), cap)
    return _backoff(attempt, base, cap)


def _backoff(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with full jitter (AWS architecture blog formulation)."""
    return random.uniform(0.0, min(cap, base * (2 ** (attempt - 1))))
