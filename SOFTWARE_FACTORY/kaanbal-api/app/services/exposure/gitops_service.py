"""ExposureGitOpsService — mutate overlays for a desired exposure mode.

Thin façade over AppDeployer helpers so the orchestrator does not call
the monolith directly. Full extraction of YAML generators is incremental.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .types import PublisherResult


class ExposureGitOpsService:
    """Applies exposure mode to rendered app overlays (Ingress / TS / delete)."""

    def __init__(self, deployer: Any = None):
        self._deployer = deployer

    async def apply_env(
        self,
        *,
        overlay_path: str,
        app_name: str,
        env: str,
        mode: str,
        app_data: Any = None,
        spec: Any = None,
        mutate_fn: Optional[Callable[..., Any]] = None,
    ) -> PublisherResult:
        name = "gitops"
        try:
            if mutate_fn:
                await _maybe_await(mutate_fn(overlay_path, app_name, env, mode))
            elif self._deployer is not None and app_data is not None:
                # Reuse existing deployer primitives for one env
                d = self._deployer
                is_tcp = bool(getattr(spec, "is_tcp", False)) if spec else False
                public_paths = getattr(spec, "public_paths", None) or []
                private_env_vars = getattr(spec, "private_env_vars", None) or []
                base_path = overlay_path.replace(f"overlays/{env}", "base").replace(
                    f"overlays\\{env}", "base"
                )

                if mode in ("tailscale", "both") and not is_tcp:
                    await d._generate_tailscale_ingress(
                        overlay_path, app_name, env, app_data, spec
                    )
                if mode == "both" and public_paths and not is_tcp:
                    d._generate_webhook_ingress(
                        overlay_path, app_name, env, public_paths, app_data, spec
                    )
                if mode in ("tailscale", "internal", "off") and not is_tcp:
                    d._upsert_ingress_delete_patch(overlay_path, app_name)
                if mode in ("public", "both") and not is_tcp:
                    d._ensure_nginx_ingress_for_public(
                        overlay_path, app_name, env, app_data
                    )
                    d._upsert_ingress_host_patch(
                        overlay_path, app_name, env, app_data, app_name
                    )
                if mode == "tailscale":
                    d._patch_env_domains_for_exposure(
                        overlay_path, base_path, app_name, env, "tailscale"
                    )
                elif mode == "both" and private_env_vars:
                    d._patch_env_domains_for_exposure(
                        overlay_path, base_path, app_name, env, "both",
                        private_env_vars=private_env_vars,
                    )
            else:
                return PublisherResult(
                    name=name, ok=False, status="failed",
                    detail="no deployer/mutate_fn configured",
                )
            return PublisherResult(
                name=name, ok=True, status="ok",
                detail=f"overlays updated for {app_name}/{env} mode={mode}",
                meta={"mode": mode, "env": env, "app": app_name},
            )
        except Exception as exc:  # noqa: BLE001
            return PublisherResult(
                name=name, ok=False, status="failed",
                detail=f"{type(exc).__name__}: {exc}",
            )


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
