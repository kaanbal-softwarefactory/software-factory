"""LifecycleService — stop/start/scale (Fase 2 API will call this)."""
from __future__ import annotations

from typing import Any, Optional

from .types import PublisherResult


class LifecycleService:
    async def scale(
        self, *, app_name: str, env: str, replicas: int, apply_fn=None
    ) -> PublisherResult:
        if apply_fn:
            await apply_fn(app_name, env, replicas)
        return PublisherResult(
            name="lifecycle", ok=True, status="ok",
            detail=f"scale {app_name}/{env} → {replicas}",
            meta={"replicas": replicas},
        )

    async def stop(self, *, app_name: str, env: str, apply_fn=None) -> PublisherResult:
        return await self.scale(app_name=app_name, env=env, replicas=0, apply_fn=apply_fn)

    async def start(
        self, *, app_name: str, env: str, replicas: int = 1, apply_fn=None
    ) -> PublisherResult:
        return await self.scale(
            app_name=app_name, env=env, replicas=max(1, replicas), apply_fn=apply_fn
        )
