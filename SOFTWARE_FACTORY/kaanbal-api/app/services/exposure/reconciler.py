"""GitOpsReconcilerService — push + wait Argo (retry wrapper)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from .retry import with_retries
from .types import PublisherResult


class GitOpsReconcilerService:
    def __init__(self, wait_fn: Optional[Callable[[], Awaitable[bool]]] = None):
        self._wait_fn = wait_fn

    async def reconcile(self, *, label: str = "argo") -> PublisherResult:
        name = "gitops_reconciler"

        async def _once() -> PublisherResult:
            if not self._wait_fn:
                return PublisherResult(
                    name=name, ok=True, status="pending",
                    detail="no wait_fn — Argo will sync asynchronously",
                )
            ok = bool(await self._wait_fn())
            return PublisherResult(
                name=name, ok=ok,
                status="ok" if ok else "pending",
                detail=f"reconcile {label}: {'healthy' if ok else 'not ready'}",
            )

        return await with_retries(
            name, _once, attempts=6, base_delay=3.0, max_delay=20.0,
            retryable=lambda r: r.status == "pending",
        )
