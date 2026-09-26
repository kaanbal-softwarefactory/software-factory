"""Async retry helper for transient publisher failures."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional, TypeVar

from .types import PublisherResult

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def with_retries(
    name: str,
    fn: Callable[[], Awaitable[PublisherResult]],
    *,
    attempts: int = 5,
    base_delay: float = 1.5,
    max_delay: float = 20.0,
    retryable: Optional[Callable[[PublisherResult], bool]] = None,
) -> PublisherResult:
    """Run ``fn`` with exponential backoff.

    Retries when ``result.ok`` is False and ``status`` is not ``skipped``,
    or when ``retryable(result)`` returns True.
    """
    last: Optional[PublisherResult] = None
    for i in range(1, attempts + 1):
        try:
            result = await fn()
        except Exception as exc:  # noqa: BLE001 — publishers own their errors
            result = PublisherResult(
                name=name, ok=False, status="failed",
                attempts=i, detail=f"{type(exc).__name__}: {exc}",
            )
        result.attempts = i
        last = result
        should_retry = (not result.ok) and result.status not in ("skipped",)
        if retryable is not None:
            should_retry = retryable(result)
        if result.ok or not should_retry or i >= attempts:
            return result
        delay = min(max_delay, base_delay * (2 ** (i - 1)))
        logger.info("publisher %s attempt %s failed (%s); retry in %.1fs",
                    name, i, result.detail, delay)
        await asyncio.sleep(delay)
    return last or PublisherResult(name=name, ok=False, status="failed", detail="no attempts")
