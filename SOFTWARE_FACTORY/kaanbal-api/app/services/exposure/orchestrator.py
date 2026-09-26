"""ExposureOrchestrator — anti-race order across independent publishers."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .dns_publisher import DnsPublisherService
from .tailscale_publisher import TailscalePublisherService
from .types import PublisherResult, merge_results

logger = logging.getLogger(__name__)

EmitFn = Callable[..., Awaitable[None]]


class ExposureOrchestrator:
    """Coordinates publishers without burying DNS/TS waits inside GitOps.

    Safe order:
      1) bindings (optional callback)
      2) gitops apply (optional callback — mutate overlays + push)
      3) argo wait (optional callback)
      4) parallel: dns ∥ tailscale ∥ lan
      5) aggregate connection_info
    """

    def __init__(
        self,
        dns: Optional[DnsPublisherService] = None,
        tailscale: Optional[TailscalePublisherService] = None,
    ):
        self.dns = dns or DnsPublisherService()
        self.tailscale = tailscale or TailscalePublisherService()

    async def apply_env(
        self,
        *,
        app_name: str,
        env: str,
        mode: str,
        domain: str = "",
        ts_suffix: str = "",
        public_hostname: str = "",
        magic_hostname: str = "",
        ensure_dns: bool = False,
        ensure_tailscale: bool = False,
        bindings_fn: Optional[Callable[[], Awaitable[PublisherResult]]] = None,
        gitops_fn: Optional[Callable[[], Awaitable[PublisherResult]]] = None,
        argo_fn: Optional[Callable[[], Awaitable[PublisherResult]]] = None,
        lan_fn: Optional[Callable[[], Awaitable[PublisherResult]]] = None,
        emit: Optional[EmitFn] = None,
    ) -> Dict[str, Any]:
        results: List[PublisherResult] = []

        async def _emit(step: str, msg: str, level: str = "info"):
            if emit:
                await emit(step, msg, level)

        # 1 bindings
        if bindings_fn:
            await _emit("bindings", f"{app_name}/{env}: injecting DB bindings")
            results.append(await bindings_fn())

        # 2 gitops
        if gitops_fn:
            await _emit("gitops", f"{app_name}/{env}: applying exposure overlays ({mode})")
            results.append(await gitops_fn())

        # 3 argo
        if argo_fn:
            await _emit("argo", f"{app_name}/{env}: waiting Argo sync")
            results.append(await argo_fn())

        # 4 parallel publishers
        tasks = []
        if ensure_dns and public_hostname:
            tasks.append(self.dns.publish(
                hostname=public_hostname, domain=domain, ensure=True))
        elif mode in ("internal", "off", "tailscale", "lan") and public_hostname:
            # Best-effort DNS cleanup when leaving public
            tasks.append(self.dns.publish(
                hostname=public_hostname, domain=domain, ensure=False))

        if ensure_tailscale and magic_hostname:
            tasks.append(self.tailscale.publish(
                magic_hostname=magic_hostname, ensure=True))
        elif magic_hostname and mode in ("public", "internal", "off", "lan"):
            tasks.append(self.tailscale.publish(
                magic_hostname=magic_hostname, ensure=False))

        if lan_fn and mode == "lan":
            tasks.append(lan_fn())

        if tasks:
            await _emit("publishers", f"{app_name}/{env}: DNS/Tailscale/LAN in parallel")
            parallel = await asyncio.gather(*tasks, return_exceptions=True)
            for item in parallel:
                if isinstance(item, Exception):
                    results.append(PublisherResult(
                        name="publisher", ok=False, status="failed",
                        detail=str(item),
                    ))
                else:
                    results.append(item)

        summary = merge_results(results)
        summary["app"] = app_name
        summary["env"] = env
        summary["mode"] = mode
        summary["connection_info"] = self._connection_info(
            mode=mode,
            public_hostname=public_hostname,
            magic_hostname=magic_hostname,
            domain=domain,
            app_name=app_name,
            env=env,
        )
        return summary

    @staticmethod
    def _connection_info(
        *, mode: str, public_hostname: str, magic_hostname: str,
        domain: str, app_name: str, env: str,
    ) -> Dict[str, Optional[str]]:
        cluster = f"{app_name}.{env}.svc.cluster.local"
        info = {
            "mode": mode,
            "public_url": None,
            "tailscale_url": None,
            "lan_url": None,
            "cluster_url": f"http://{cluster}",
            "status": "off" if mode == "off" else "active",
        }
        if mode in ("public", "both") and public_hostname:
            info["public_url"] = f"https://{public_hostname}"
        if mode in ("tailscale", "both") and magic_hostname:
            info["tailscale_url"] = f"http://{magic_hostname}"
        return info
