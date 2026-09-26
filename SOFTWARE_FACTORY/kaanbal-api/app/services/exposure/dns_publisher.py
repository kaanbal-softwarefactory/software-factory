"""DnsPublisherService — Cloudflare DNS with retries (independent of GitOps)."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .retry import with_retries
from .types import PublisherResult

logger = logging.getLogger(__name__)


class DnsPublisherService:
    """Create or delete public DNS records for an app env.

    Does not mutate Kubernetes. Safe to retry; Cloudflare upserts by name.
    """

    def __init__(self, cloudflare_client: Any = None):
        self._cf = cloudflare_client

    async def publish(
        self,
        *,
        hostname: str,
        domain: str,
        ensure: bool = True,
        create_fn: Optional[Callable[..., Any]] = None,
        delete_fn: Optional[Callable[..., Any]] = None,
    ) -> PublisherResult:
        name = "dns"

        async def _once() -> PublisherResult:
            if not ensure:
                if delete_fn:
                    await _maybe_await(delete_fn(hostname))
                return PublisherResult(
                    name=name, ok=True, status="ok",
                    detail=f"DNS removed or skipped for {hostname}",
                    urls=[],
                )
            created = True
            if create_fn:
                created = await _maybe_await(create_fn(hostname))
                if created is None:
                    created = True
            url = f"https://{hostname}" if domain else hostname
            if not created:
                return PublisherResult(
                    name=name, ok=False, status="pending",
                    detail=f"DNS not configured or not yet ready for {hostname}",
                    urls=[],
                    meta={"hostname": hostname},
                )
            return PublisherResult(
                name=name, ok=True, status="ok",
                detail=f"DNS ensured for {hostname}",
                urls=[url],
                meta={"hostname": hostname},
            )

        return await with_retries(name, _once, attempts=5, base_delay=2.0)


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
