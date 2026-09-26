"""TailscalePublisherService — wait for MagicDNS device after annotations."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .retry import with_retries
from .types import PublisherResult

logger = logging.getLogger(__name__)


class TailscalePublisherService:
    """Verifies Tailscale proxy/device is online for a hostname.

    Overlay annotations are applied by ExposureGitOpsService; this publisher
    only polls until the device appears (avoids race with operator).
    """

    def __init__(self, list_devices_fn: Optional[Callable[[], Any]] = None):
        self._list_devices = list_devices_fn

    async def publish(
        self,
        *,
        magic_hostname: str,
        ensure: bool = True,
        probe_fn: Optional[Callable[[], Any]] = None,
    ) -> PublisherResult:
        name = "tailscale"

        if not ensure:
            return PublisherResult(
                name=name, ok=True, status="skipped",
                detail="Tailscale exposure not requested",
            )

        async def _once() -> PublisherResult:
            online = False
            detail = "no probe"
            if probe_fn:
                online = bool(await _maybe_await(probe_fn()))
                detail = "probe ok" if online else "device not online yet"
            elif self._list_devices:
                devices = await _maybe_await(self._list_devices())
                names = {
                    (d.get("name") or d.get("hostname") or "").lower()
                    for d in (devices or [])
                }
                short = magic_hostname.lower().split(".")[0]
                online = (
                    magic_hostname.lower() in names
                    or short in names
                    or any(short in n or magic_hostname.lower() in n for n in names if n)
                )
                detail = "device listed" if online else "device missing from Tailscale API"
            else:
                # Without credentials we mark pending rather than fail the deploy.
                return PublisherResult(
                    name=name, ok=True, status="pending",
                    detail="no Tailscale probe configured",
                    urls=[f"http://{magic_hostname}"],
                )

            return PublisherResult(
                name=name, ok=online, status="ok" if online else "pending",
                detail=detail,
                urls=[f"http://{magic_hostname}"] if online else [],
                meta={"hostname": magic_hostname},
            )

        def _retryable(r: PublisherResult) -> bool:
            return r.status == "pending" or (not r.ok and r.status != "skipped")

        return await with_retries(
            name, _once, attempts=8, base_delay=2.0, max_delay=15.0,
            retryable=_retryable,
        )


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
