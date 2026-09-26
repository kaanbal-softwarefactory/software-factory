"""Exposure switch + lifecycle (Fase 2) — post-deploy mode changes."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.defaults import EXPOSURE_RULES, EXPOSURE_RULES_DEFAULT, TAILSCALE_DNS_SUFFIX
from app.services.exposure.dns_publisher import DnsPublisherService
from app.services.exposure.gitops_service import ExposureGitOpsService
from app.services.exposure.inventory import (
    apply_observed,
    build_desired_inventory,
    summarize_inventory,
)
from app.services.exposure.lifecycle import LifecycleService
from app.services.exposure.orchestrator import ExposureOrchestrator
from app.services.exposure.probes import (
    get_ingress_hosts,
    get_ts_service_ready,
    wait_projection,
    wait_public_http,
)
from app.services.exposure.tailscale_publisher import TailscalePublisherService
from app.services.exposure.types import PublisherResult, merge_results

logger = logging.getLogger(__name__)

VALID_MODES = {"public", "tailscale", "both", "lan", "internal", "off"}


class ExposureSwitchService:
    """Change per-env exposure after deploy without full redeploy."""

    def __init__(self, deployer: Any):
        self.deployer = deployer
        self.gitops = ExposureGitOpsService(deployer)
        self.dns = DnsPublisherService()
        self.ts = TailscalePublisherService()
        self.lifecycle = LifecycleService()
        self.orch = ExposureOrchestrator(dns=self.dns, tailscale=self.ts)

    def _mode_value(self, mode) -> str:
        if hasattr(mode, "value"):
            return str(mode.value)
        return str(mode or "internal").lower()

    def validate_modes(self, category: Optional[str], per_env: Dict[str, str]) -> None:
        allowed = EXPOSURE_RULES.get(category or "", EXPOSURE_RULES_DEFAULT)
        # off always allowed for lifecycle
        allowed = list(allowed) + (["off"] if "off" not in allowed else [])
        for env, mode in per_env.items():
            m = self._mode_value(mode)
            if m not in VALID_MODES:
                raise ValueError(f"Invalid exposure mode '{m}' for env '{env}'")
            if m not in allowed and m != "off":
                raise ValueError(
                    f"Exposure '{m}' not allowed for category '{category}' "
                    f"(allowed: {', '.join(allowed)})"
                )

    async def switch(
        self,
        *,
        app_doc: dict,
        per_env: Dict[str, str],
        port_exposure: Optional[Dict[str, Dict[str, str]]] = None,
        target_domain_id: Optional[str] = None,
        actor: str = "system",
    ) -> Dict[str, Any]:
        await self.deployer._load_credentials()
        app_name = app_doc["name"]

        # Multi-dominio: atarse al dominio actual de la app antes de calcular
        # nada. Si además se pide mudar de dominio padre, se capturan primero
        # los hosts viejos —los registros DNS a retirar al final— y recién
        # después se rebindea, para que overlays, TLS y DNS nuevos se generen
        # ya sobre el dominio destino.
        await self.deployer.bind_domain(app_doc=app_doc)
        previous_domain = self.deployer.domain
        previous_domain_id = (self.deployer._domain_ctx or {}).get("domain_id")
        domain_changed = False
        stale_public_hosts: List[str] = []

        if target_domain_id and str(target_domain_id) != str(previous_domain_id or ""):
            spec_shim = _AppShim(app_doc, dict(app_doc.get("exposure") or {}))
            prior_per = dict((app_doc.get("exposure") or {}).get("per_env") or {})
            for env, mode in prior_per.items():
                if self._mode_value(mode) in ("public", "both"):
                    stale_public_hosts.append(
                        self.deployer._build_public_host(app_name, env, spec_shim)
                    )
            await self.deployer.bind_domain(domain_id=target_domain_id)
            domain_changed = True
            logger.info(
                "App %s switching parent domain: %s -> %s",
                app_name, previous_domain, self.deployer.domain,
            )
            # Cambiar de dominio mueve el FQDN de TODOS los ambientes públicos,
            # no solo los que venían en el PATCH: se republican todos para que
            # cada uno reciba su DNS y su probe en el dominio nuevo.
            per_env = {
                **{env: self._mode_value(mode) for env, mode in prior_per.items()},
                **{env: self._mode_value(mode) for env, mode in per_env.items()},
            }

        category = app_doc.get("category")
        environments = app_doc.get("environments") or list(per_env.keys()) or ["prod"]
        self.validate_modes(category, per_env)

        previous_per = dict((app_doc.get("exposure") or {}).get("per_env") or {})
        exposure = dict(app_doc.get("exposure") or {})
        existing_per = dict(exposure.get("per_env") or {})
        for env, mode in per_env.items():
            existing_per[env] = self._mode_value(mode)
        exposure["per_env"] = existing_per
        if port_exposure is not None:
            exposure["port_exposure"] = port_exposure
        if "prod" in existing_per:
            exposure["type"] = existing_per["prod"]
        elif existing_per:
            exposure["type"] = next(iter(existing_per.values()))

        app_data = _AppShim(app_doc, exposure)
        spec = await self._resolve_spec(app_doc)

        work = tempfile.mkdtemp(prefix="kaanbal-switch-")
        infra_path = os.path.join(work, "infra-gitops")
        results: List[PublisherResult] = []
        try:
            auth_url = self.deployer.provider.get_auth_clone_url("infra-gitops")
            import subprocess
            rc = subprocess.run(
                ["git", "clone", "--depth", "1", auth_url, infra_path],
                capture_output=True, text=True, timeout=180,
            )
            if rc.returncode != 0:
                raise RuntimeError(f"clone infra-gitops failed: {(rc.stderr or '')[:200]}")

            app_dir = os.path.join(infra_path, "apps", app_name)
            if not os.path.isdir(app_dir):
                raise RuntimeError(f"app overlays not found in infra-gitops: apps/{app_name}")

            for env, mode in existing_per.items():
                if env not in environments and env not in per_env:
                    continue
                overlay = os.path.join(app_dir, "overlays", env)
                if not os.path.isdir(overlay):
                    results.append(PublisherResult(
                        name="gitops", ok=False, status="failed",
                        detail=f"missing overlay {env}",
                    ))
                    continue
                gr = await self.gitops.apply_env(
                    overlay_path=overlay,
                    app_name=app_name,
                    env=env,
                    mode=self._mode_value(mode),
                    app_data=app_data,
                    spec=spec,
                )
                results.append(gr)

                # Only touch replicas for off / leaving-off — never on plain
                # public↔tailscale switches (avoids bogus STS patches on Deployments).
                new_mode = self._mode_value(mode)
                old_mode = self._mode_value(previous_per.get(env, ""))
                if new_mode == "off":
                    self._write_replicas_patch(overlay, app_name, 0)
                elif env in per_env and old_mode == "off" and new_mode != "off":
                    self._write_replicas_patch(
                        overlay,
                        app_name,
                        max(1, int((app_doc.get("specs") or {}).get("replicas") or 1)),
                    )

            envs_touched = sorted(per_env.keys())
            await self.deployer._push_infra(infra_path, app_name, envs_touched or environments)
            results.append(PublisherResult(
                name="gitops_reconciler", ok=True, status="ok",
                detail="infra-gitops pushed; ArgoCD will sync",
            ))

            ts_suffix = (
                self.deployer._credentials.get("tailscale_dns_suffix")
                or TAILSCALE_DNS_SUFFIX
            )
            domain = getattr(self.deployer, "domain", "") or ""

            def _public_host(env: str) -> str:
                return self.deployer._build_public_host(app_name, env, app_data)

            inventory = build_desired_inventory(
                app_name=app_name,
                per_env={e: self._mode_value(m) for e, m in existing_per.items()},
                public_host_fn=_public_host,
                ts_suffix=ts_suffix,
                category=category or "",
            )

            async def _list_devices():
                token = await self.deployer._get_tailscale_api_token()
                if not token:
                    return []
                return await self.deployer._list_tailscale_devices(token)

            self.ts = TailscalePublisherService(list_devices_fn=_list_devices)

            for env, mode in per_env.items():
                m = self._mode_value(mode)
                public_host = _public_host(env)
                magic = f"{env}-{app_name}.{ts_suffix}"
                magic_short = f"{env}-{app_name}"
                _hosts = [public_host]
                row = inventory["by_env"].get(env) or {}

                # Gate 1 — wait Argo projection (Ingress / TS Service)
                proj = await wait_projection(
                    app_name=app_name,
                    env=env,
                    mode=m,
                    expected_public_host=public_host,
                )
                results.append(PublisherResult(
                    name=f"projection:{env}",
                    ok=bool(proj.get("ok")),
                    status="ok" if proj.get("ok") else "pending",
                    detail=proj.get("detail") or "",
                    meta={"canonical_public_host": public_host},
                ))

                async def _dns_create(h, hosts=_hosts):
                    return await self.deployer._setup_cloudflare_dns(app_name, hosts)

                async def _dns_delete(h, hosts=_hosts):
                    return await self.deployer._delete_cloudflare_dns(hosts)

                async def _ts_probe(short=magic_short, fqdn=magic, env_name=env):
                    ts = await get_ts_service_ready(env_name, app_name)
                    proxy_ok = bool(ts.get("ready")) or await self._wait_proxy_ready(
                        app_name, env_name, attempts=1
                    )
                    devices = await _list_devices()
                    names = {
                        (d.get("name") or d.get("hostname") or "").lower()
                        for d in (devices or [])
                    }
                    listed = (
                        fqdn.lower() in names
                        or short.lower() in names
                        or any(short.lower() in n for n in names)
                    )
                    return bool(proxy_ok and listed)

                ensure_dns = m in ("public", "both")
                dns_r = await self.dns.publish(
                    hostname=public_host,
                    domain=domain,
                    ensure=ensure_dns,
                    create_fn=_dns_create if ensure_dns else None,
                    delete_fn=_dns_delete if not ensure_dns else None,
                )
                dns_r.name = f"dns:{env}"
                dns_r.meta = {**(dns_r.meta or {}), "canonical_host": public_host}
                results.append(dns_r)

                ensure_ts = m in ("tailscale", "both")
                if ensure_ts:
                    ts_r = await self.ts.publish(
                        magic_hostname=magic,
                        ensure=True,
                        probe_fn=_ts_probe,
                    )
                else:
                    ts_r = await self.ts.publish(magic_hostname=magic, ensure=False)
                ts_r.name = f"tailscale:{env}"
                results.append(ts_r)

                # Gate 2 — public HTTP probe on CANONICAL host (prod = app.domain)
                http_probe = None
                if m in ("public", "both"):
                    url = f"https://{public_host}/"
                    http_probe = await wait_public_http(url)
                    results.append(PublisherResult(
                        name=f"http:{env}",
                        ok=bool(http_probe.get("ok")),
                        status="ok" if http_probe.get("ok") else "pending",
                        detail=(
                            f"{http_probe.get('detail')} url={url} "
                            f"(canonical; not prod-{{app}} unless env!=prod)"
                        ),
                        urls=[url] if http_probe.get("ok") else [],
                        meta={"canonical_public_host": public_host},
                    ))

                # Refresh observed inventory for this env
                hosts = proj.get("ingress_hosts")
                if hosts is None:
                    hosts = await get_ingress_hosts(env, app_name)
                ts_obs = proj.get("ts") or await get_ts_service_ready(env, app_name)
                devices = await _list_devices() if ensure_ts else []
                names = {
                    (d.get("name") or d.get("hostname") or "").lower()
                    for d in (devices or [])
                }
                listed = (
                    magic.lower() in names
                    or magic_short.lower() in names
                    or any(magic_short.lower() in n for n in names)
                ) if ensure_ts else None

                inventory["by_env"][env] = apply_observed(
                    row,
                    ingress_hosts=hosts,
                    ts=ts_obs,
                    http_probe=http_probe,
                    ts_device_listed=listed,
                    cf_ok=bool(dns_r.ok) if ensure_dns else None,
                )

            # Retirar el DNS del dominio anterior solo cuando el nuevo ya
            # publicó bien. Borrar antes dejaría la app sin ningún host vivo si
            # el dominio destino todavía no resuelve.
            if domain_changed and stale_public_hosts:
                new_dns_ok = all(
                    r.ok for r in results if r.name and r.name.startswith("dns:")
                )
                if new_dns_ok:
                    await self.deployer.bind_domain(domain_id=previous_domain_id)
                    try:
                        await self.deployer._delete_cloudflare_dns(stale_public_hosts)
                        results.append(PublisherResult(
                            name="dns:retire-previous", ok=True, status="ok",
                            detail=f"removed {', '.join(stale_public_hosts)} from {previous_domain}",
                        ))
                    finally:
                        await self.deployer.bind_domain(domain_id=target_domain_id)
                else:
                    results.append(PublisherResult(
                        name="dns:retire-previous", ok=True, status="pending",
                        detail=(
                            f"kept {', '.join(stale_public_hosts)} on {previous_domain}: "
                            "the new domain has not published yet"
                        ),
                    ))

            # Keep prior observed for envs not touched in this PATCH
            prev_by = ((app_doc.get("connection_inventory") or {}).get("by_env") or {})
            for env, row in list((inventory.get("by_env") or {}).items()):
                if env in per_env:
                    continue
                if env in prev_by:
                    inventory["by_env"][env] = prev_by[env]
                else:
                    # First inventory: observe without waiting
                    ph = _public_host(env)
                    hosts = await get_ingress_hosts(env, app_name)
                    ts_obs = await get_ts_service_ready(env, app_name)
                    m = self._mode_value(existing_per.get(env))
                    http_probe = None
                    if m in ("public", "both") and ph:
                        from app.services.exposure.probes import probe_http_url
                        http_probe = await probe_http_url(f"https://{ph}/")
                    inventory["by_env"][env] = apply_observed(
                        row, ingress_hosts=hosts, ts=ts_obs, http_probe=http_probe,
                    )

            summary = merge_results(results)
            touched_inv = {
                "by_env": {
                    e: inventory["by_env"][e]
                    for e in per_env
                    if e in (inventory.get("by_env") or {})
                }
            }
            inv_summary = summarize_inventory(touched_inv)
            full_summary = summarize_inventory(inventory)
            # Validated only when touched envs pass inventory gates (not mere git push)
            validated = bool(inv_summary.get("validated")) and bool(
                summary.get("critical_ok", True)
            )

            connection = {
                env: {
                    **(row.get("connection") or {}),
                    "surfaces": row.get("surfaces") or {},
                    "status": row.get("status"),
                    "canonical_public_host": (row.get("desired") or {}).get("public_hostname"),
                    "canonical_ts_host": (row.get("desired") or {}).get("ts_hostname"),
                }
                for env, row in (inventory.get("by_env") or {}).items()
            }
            inventory["updated_at"] = datetime.utcnow().isoformat() + "Z"
            inventory["summary"] = full_summary

            return {
                "app": app_name,
                "exposure": exposure,
                "domain": self.deployer.domain,
                "domain_id": (self.deployer._domain_ctx or {}).get("domain_id"),
                "domain_changed": domain_changed,
                "previous_domain": previous_domain if domain_changed else None,
                "connection_info": connection,
                "connection_inventory": inventory,
                "publishers": summary,
                "validated": validated,
                "drift": inv_summary.get("drift") or [],
                "pending": inv_summary.get("pending") or [],
                "actor": actor,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def refresh_status(self, *, app_doc: dict) -> Dict[str, Any]:
        """Read-only reconcile: refresh observed inventory without mutating GitOps."""
        await self.deployer._load_credentials()
        await self.deployer.bind_domain(app_doc=app_doc)
        app_name = app_doc["name"]
        category = app_doc.get("category") or ""
        exposure = dict(app_doc.get("exposure") or {})
        per_env = dict(exposure.get("per_env") or {})
        if not per_env:
            typ = self._mode_value(exposure.get("type") or "internal")
            for env in app_doc.get("environments") or ["prod"]:
                per_env[env] = typ
        app_data = _AppShim(app_doc, exposure)
        ts_suffix = (
            (self.deployer._credentials or {}).get("tailscale_dns_suffix")
            or TAILSCALE_DNS_SUFFIX
        )

        def _public_host(env: str) -> str:
            return self.deployer._build_public_host(app_name, env, app_data)

        inventory = build_desired_inventory(
            app_name=app_name,
            per_env={e: self._mode_value(m) for e, m in per_env.items()},
            public_host_fn=_public_host,
            ts_suffix=ts_suffix,
            category=category,
        )

        async def _list_devices():
            token = await self.deployer._get_tailscale_api_token()
            if not token:
                return []
            return await self.deployer._list_tailscale_devices(token)

        devices = await _list_devices()
        names = {
            (d.get("name") or d.get("hostname") or "").lower()
            for d in (devices or [])
        }

        for env, mode in per_env.items():
            m = self._mode_value(mode)
            public_host = _public_host(env)
            magic = f"{env}-{app_name}.{ts_suffix}"
            magic_short = f"{env}-{app_name}"
            hosts = await get_ingress_hosts(env, app_name)
            ts_obs = await get_ts_service_ready(env, app_name)
            http_probe = None
            if m in ("public", "both") and public_host:
                from app.services.exposure.probes import probe_http_url
                http_probe = await probe_http_url(f"https://{public_host}/")
            listed = (
                magic.lower() in names
                or magic_short.lower() in names
                or any(magic_short.lower() in n for n in names)
            ) if m in ("tailscale", "both") else None
            inventory["by_env"][env] = apply_observed(
                inventory["by_env"][env],
                ingress_hosts=hosts,
                ts=ts_obs,
                http_probe=http_probe,
                ts_device_listed=listed,
            )

        inv_summary = summarize_inventory(inventory)
        inventory["summary"] = inv_summary
        inventory["updated_at"] = datetime.utcnow().isoformat() + "Z"
        connection = {
            env: {
                **(row.get("connection") or {}),
                "surfaces": row.get("surfaces") or {},
                "status": row.get("status"),
                "canonical_public_host": (row.get("desired") or {}).get("public_hostname"),
                "canonical_ts_host": (row.get("desired") or {}).get("ts_hostname"),
            }
            for env, row in (inventory.get("by_env") or {}).items()
        }
        return {
            "app": app_name,
            "exposure": exposure,
            "connection_info": connection,
            "connection_inventory": inventory,
            "validated": bool(inv_summary.get("validated")),
            "drift": inv_summary.get("drift") or [],
            "pending": inv_summary.get("pending") or [],
            "updated_at": inventory["updated_at"],
        }

    async def _wait_proxy_ready(self, app_name: str, env: str, attempts: int = 12) -> bool:
        """Poll Service condition TailscaleProxyReady via in-cluster K8s API.

        The API pod has no kubectl binary — use the service-account token
        against kubernetes.default.svc (same pattern as apps tag patching).
        Outside the cluster (unit tests), skip and return True so device-list
        remains the authoritative probe.
        """
        import asyncio
        import ssl

        import httpx

        sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        if not os.path.exists(sa_token_path):
            logger.info("Not in-cluster — skipping TailscaleProxyReady poll for %s/%s", env, app_name)
            return True

        with open(sa_token_path) as f:
            token = f.read().strip()
        ssl_ctx = (
            ssl.create_default_context(cafile=ca_path)
            if os.path.exists(ca_path)
            else False
        )
        ns = env
        svc = f"{app_name}-ts"
        url = f"https://kubernetes.default.svc/api/v1/namespaces/{ns}/services/{svc}"
        headers = {"Authorization": f"Bearer {token}"}

        for i in range(attempts):
            try:
                async with httpx.AsyncClient(verify=ssl_ctx, timeout=15) as client:
                    resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    conditions = (resp.json().get("status") or {}).get("conditions") or []
                    for c in conditions:
                        if (
                            c.get("type") == "TailscaleProxyReady"
                            and str(c.get("status")) == "True"
                        ):
                            return True
                elif resp.status_code == 404:
                    logger.debug("TS service %s/%s not found yet", ns, svc)
                else:
                    logger.warning(
                        "proxy ready probe %s/%s: HTTP %s", ns, svc, resp.status_code
                    )
            except Exception as e:
                logger.warning("proxy ready probe %s/%s: %s", ns, svc, e)
            await asyncio.sleep(min(2 + i, 8))
        return False

    async def scale_env(
        self, *, app_doc: dict, env: str, replicas: int, actor: str = "system"
    ) -> Dict[str, Any]:
        await self.deployer._load_credentials()
        app_name = app_doc["name"]
        if replicas < 0:
            raise ValueError("replicas must be >= 0")

        work = tempfile.mkdtemp(prefix="kaanbal-scale-")
        infra_path = os.path.join(work, "infra-gitops")
        try:
            auth_url = self.deployer.provider.get_auth_clone_url("infra-gitops")
            import subprocess
            rc = subprocess.run(
                ["git", "clone", "--depth", "1", auth_url, infra_path],
                capture_output=True, text=True, timeout=180,
            )
            if rc.returncode != 0:
                raise RuntimeError(f"clone failed: {(rc.stderr or '')[:200]}")
            overlay = os.path.join(infra_path, "apps", app_name, "overlays", env)
            if not os.path.isdir(overlay):
                raise RuntimeError(f"overlay not found: {env}")
            self._write_replicas_patch(overlay, app_name, replicas)
            await self.deployer._push_infra(infra_path, app_name, [env])
            lr = await self.lifecycle.scale(
                app_name=app_name, env=env, replicas=replicas
            )
            status = "offline" if replicas == 0 else "healthy"
            return {
                "app": app_name,
                "env": env,
                "replicas": replicas,
                "status": status,
                "lifecycle": lr.to_dict(),
                "actor": actor,
            }
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def ensure_env(
        self,
        *,
        app_doc: dict,
        env: str,
        exposure_mode: str = "tailscale",
        actor: str = "system",
    ) -> Dict[str, Any]:
        """Create missing overlay (clone from existing env) and register environment."""
        await self.deployer._load_credentials()
        await self.deployer.bind_domain(app_doc=app_doc)
        app_name = app_doc["name"]
        env = (env or "").strip().lower()
        if env not in ("dev", "staging", "prod"):
            raise ValueError("env must be one of: dev, staging, prod")
        mode = self._mode_value(exposure_mode)
        self.validate_modes(app_doc.get("category"), {env: mode})

        environments = list(app_doc.get("environments") or [])
        work = tempfile.mkdtemp(prefix="kaanbal-ensure-env-")
        infra_path = os.path.join(work, "infra-gitops")
        try:
            auth_url = self.deployer.provider.get_auth_clone_url("infra-gitops")
            import subprocess
            rc = subprocess.run(
                ["git", "clone", "--depth", "1", auth_url, infra_path],
                capture_output=True, text=True, timeout=180,
            )
            if rc.returncode != 0:
                raise RuntimeError(f"clone failed: {(rc.stderr or '')[:200]}")

            app_dir = os.path.join(infra_path, "apps", app_name)
            overlays = os.path.join(app_dir, "overlays")
            target = os.path.join(overlays, env)
            if not os.path.isdir(app_dir):
                raise RuntimeError(f"app overlays not found: apps/{app_name}")

            created_overlay = False
            if not os.path.isdir(target):
                # Prefer cloning from an existing env overlay
                donors = [e for e in ("prod", "staging", "dev") if e != env]
                donor_path = None
                for d in donors:
                    p = os.path.join(overlays, d)
                    if os.path.isdir(p):
                        donor_path = p
                        break
                if not donor_path:
                    raise RuntimeError("no donor overlay to clone for new environment")
                shutil.copytree(donor_path, target)
                created_overlay = True

            if env not in environments:
                environments.append(env)

            # Push overlay creation first if needed
            if created_overlay:
                await self.deployer._push_infra(infra_path, app_name, [env])

            # Apply exposure for the new/enabled env
            updated_doc = dict(app_doc)
            updated_doc["environments"] = environments
            switch_result = await self.switch(
                app_doc=updated_doc,
                per_env={env: mode},
                actor=actor,
            )
            return {
                "app": app_name,
                "env": env,
                "created_overlay": created_overlay,
                "environments": environments,
                "exposure": switch_result.get("exposure"),
                "connection_info": switch_result.get("connection_info"),
                "publishers": switch_result.get("publishers"),
                "actor": actor,
            }
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def remove_env(
        self,
        *,
        app_doc: dict,
        env: str,
        actor: str = "system",
        delete_overlay: bool = False,
    ) -> Dict[str, Any]:
        """Stop env (replicas=0), set exposure off, drop from environments list."""
        await self.deployer._load_credentials()
        await self.deployer.bind_domain(app_doc=app_doc)
        app_name = app_doc["name"]
        env = (env or "").strip().lower()
        environments = list(app_doc.get("environments") or [])
        if env not in environments:
            raise ValueError(f"Environment '{env}' is not active for this app")
        if len(environments) <= 1:
            raise ValueError("Cannot remove the last environment — delete the app instead")

        # Scale to 0 + exposure off
        scale_result = await self.scale_env(
            app_doc=app_doc, env=env, replicas=0, actor=actor
        )
        switch_result = await self.switch(
            app_doc=app_doc, per_env={env: "off"}, actor=actor
        )

        environments = [e for e in environments if e != env]

        if delete_overlay:
            work = tempfile.mkdtemp(prefix="kaanbal-rm-env-")
            infra_path = os.path.join(work, "infra-gitops")
            try:
                auth_url = self.deployer.provider.get_auth_clone_url("infra-gitops")
                import subprocess
                rc = subprocess.run(
                    ["git", "clone", "--depth", "1", auth_url, infra_path],
                    capture_output=True, text=True, timeout=180,
                )
                if rc.returncode != 0:
                    raise RuntimeError(f"clone failed: {(rc.stderr or '')[:200]}")
                target = os.path.join(infra_path, "apps", app_name, "overlays", env)
                if os.path.isdir(target):
                    shutil.rmtree(target)
                    await self.deployer._push_infra(infra_path, app_name, [env])
            finally:
                shutil.rmtree(work, ignore_errors=True)

        return {
            "app": app_name,
            "env": env,
            "environments": environments,
            "scale": scale_result,
            "exposure": switch_result.get("exposure"),
            "connection_info": switch_result.get("connection_info"),
            "publishers": switch_result.get("publishers"),
            "actor": actor,
        }

    def _detect_workload_kinds(self, overlay_path: str, app_name: str) -> set:
        """Return {'Deployment'} and/or {'StatefulSet'} present under the app."""
        kinds = set()
        app_dir = os.path.dirname(os.path.dirname(overlay_path))  # .../apps/{name}
        scan_roots = [overlay_path]
        base = os.path.join(app_dir, "base")
        if os.path.isdir(base):
            scan_roots.append(base)
        for root in scan_roots:
            for dirpath, _, files in os.walk(root):
                for fname in files:
                    if not fname.endswith((".yaml", ".yml")):
                        continue
                    # Ignore our own replica patches when detecting
                    if fname.startswith("patch-replicas"):
                        continue
                    try:
                        text = open(os.path.join(dirpath, fname), encoding="utf-8").read()
                    except OSError:
                        continue
                    if "kind: StatefulSet" in text:
                        kinds.add("StatefulSet")
                    if "kind: Deployment" in text:
                        kinds.add("Deployment")
        if not kinds:
            kinds.add("Deployment")
        return kinds

    def _write_replicas_patch(self, overlay_path: str, app_name: str, replicas: int) -> None:
        kinds = self._detect_workload_kinds(overlay_path, app_name)
        kust = os.path.join(overlay_path, "kustomization.yaml")
        kust_text = open(kust, encoding="utf-8").read() if os.path.isfile(kust) else ""

        def _ensure_listed(filename: str, text: str) -> str:
            if filename in text:
                return text
            if "patchesStrategicMerge:" in text:
                return text.replace(
                    "patchesStrategicMerge:",
                    f"patchesStrategicMerge:\n  - {filename}",
                    1,
                )
            if "\npatches:" in text or text.strip().startswith("patches:"):
                # Prefer appending a strategic-merge list (compatible with older overlays)
                return text.rstrip() + f"\npatchesStrategicMerge:\n  - {filename}\n"
            return text.rstrip() + f"\npatchesStrategicMerge:\n  - {filename}\n"

        # Drop stale STS patch if this app is Deployment-only (fixes prior broken switches)
        sts_path = os.path.join(overlay_path, "patch-replicas-sts.yaml")
        dep_path = os.path.join(overlay_path, "patch-replicas.yaml")

        if "Deployment" in kinds:
            content = (
                f"apiVersion: apps/v1\n"
                f"kind: Deployment\n"
                f"metadata:\n"
                f"  name: {app_name}\n"
                f"spec:\n"
                f"  replicas: {replicas}\n"
            )
            with open(dep_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            if os.path.isfile(kust):
                kust_text = _ensure_listed("patch-replicas.yaml", kust_text)
        else:
            if os.path.isfile(dep_path):
                os.remove(dep_path)
            kust_text = "\n".join(
                ln for ln in kust_text.splitlines() if "patch-replicas.yaml" not in ln
            ) + ("\n" if kust_text else "")

        if "StatefulSet" in kinds:
            sts = (
                f"apiVersion: apps/v1\n"
                f"kind: StatefulSet\n"
                f"metadata:\n"
                f"  name: {app_name}\n"
                f"spec:\n"
                f"  replicas: {replicas}\n"
            )
            with open(sts_path, "w", encoding="utf-8") as fh:
                fh.write(sts)
            if os.path.isfile(kust):
                kust_text = _ensure_listed("patch-replicas-sts.yaml", kust_text)
        else:
            if os.path.isfile(sts_path):
                os.remove(sts_path)
            kust_text = "\n".join(
                ln for ln in kust_text.splitlines()
                if "patch-replicas-sts.yaml" not in ln
            ) + ("\n" if kust_text else "")

        if os.path.isfile(kust) and kust_text.strip():
            open(kust, "w", encoding="utf-8").write(kust_text)

    async def _resolve_spec(self, app_doc: dict):
        try:
            from app.services.template_service import TemplateService
            ts = TemplateService()
            tpl = app_doc.get("template") or ""
            # Best-effort; GitOps helpers tolerate None spec
            return await ts.get_spec(tpl) if hasattr(ts, "get_spec") else None
        except Exception:
            return None


class _AppShim:
    """Minimal stand-in for AppCreate used by deployer overlay helpers."""

    def __init__(self, app_doc: dict, exposure: dict):
        self.name = app_doc["name"]
        self.template = app_doc.get("template")
        self.category = app_doc.get("category")
        self.environments = app_doc.get("environments") or ["prod"]
        self.template_config = app_doc.get("template_config") or {}
        # El homepage vive en la raíz del dominio: sin este dato los overlays y
        # el DNS se regeneraban como <app>.<dominio>.
        self.is_root_domain = bool(app_doc.get("is_root_domain"))
        self.exposure = _ExposureShim(exposure)
        specs = app_doc.get("specs") or {}
        self.specs = type("S", (), {"replicas": specs.get("replicas", 1), "port": specs.get("port", 80)})()


class _ExposureShim:
    def __init__(self, exposure: dict):
        self.type = exposure.get("type") or "internal"
        self.per_env = exposure.get("per_env") or {}
        self.port_exposure = exposure.get("port_exposure")
        self.public_path = exposure.get("public_path") or "/"
        self.tailscale_hostname = exposure.get("tailscale_hostname")
