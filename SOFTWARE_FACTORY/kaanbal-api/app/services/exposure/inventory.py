"""Connection inventory — desired vs observed surfaces (source of truth in Mongo)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .connection_surfaces import build_env_surfaces, infer_surfaces


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _mode(m: Any) -> str:
    if hasattr(m, "value"):
        return str(m.value).lower()
    return str(m or "internal").lower()


def build_desired_env(
    *,
    app_name: str,
    env: str,
    mode: str,
    public_hostname: str,
    ts_hostname: str,
    ts_suffix: str,
    category: str = "",
    service_port: int = 80,
) -> Dict[str, Any]:
    """One env row: primary surface + channel metadata."""
    mode = _mode(mode)
    surfaces_info = build_env_surfaces(
        mode=mode,
        public_hostname=public_hostname,
        ts_hostname=ts_hostname,
        ts_suffix=ts_suffix,
        app_name=app_name,
        env=env,
        category=category or "",
        surfaces=infer_surfaces(category=category or ""),
    )
    channel = "cluster"
    hostname = f"{app_name}.{env}.svc.cluster.local"
    if mode in ("public", "both"):
        channel = "public"
        hostname = public_hostname
    elif mode == "tailscale":
        channel = "tailscale"
        hostname = f"{ts_hostname}.{ts_suffix}" if ts_suffix and not ts_hostname.endswith(".ts.net") else ts_hostname
    elif mode == "lan":
        channel = "lan"
        hostname = ""
    elif mode == "off":
        channel = "off"
        hostname = ""

    primary_url = (
        surfaces_info.get("public_url")
        or surfaces_info.get("tailscale_url")
        or surfaces_info.get("editor_url")
        or surfaces_info.get("cluster_url")
    )

    return {
        "env": env,
        "surface_key": "primary",
        "desired": {
            "mode": mode,
            "channel": channel,
            "hostname": hostname,
            "public_hostname": public_hostname,
            "ts_hostname": (
                f"{ts_hostname}.{ts_suffix}" if ts_suffix and "." not in ts_hostname else ts_hostname
            ),
            "service": app_name,
            "ts_service": f"{app_name}-ts",
            "port": service_port,
            "path": "/",
            "url": primary_url,
        },
        "observed": {},
        "status": "pending",
        "updated_at": _now(),
        "last_error": None,
        "surfaces": surfaces_info.get("surfaces") or {},
        "connection": {
            "public_url": surfaces_info.get("public_url"),
            "tailscale_url": surfaces_info.get("tailscale_url"),
            "cluster_url": surfaces_info.get("cluster_url"),
            "mode": mode,
        },
    }


def build_desired_inventory(
    *,
    app_name: str,
    per_env: Dict[str, str],
    public_host_fn,
    ts_suffix: str,
    category: str = "",
) -> Dict[str, Any]:
    """Map env → inventory row (desired only)."""
    rows: Dict[str, Any] = {}
    for env, mode in per_env.items():
        public_host = public_host_fn(env)
        ts_short = f"{env}-{app_name}"
        rows[env] = build_desired_env(
            app_name=app_name,
            env=env,
            mode=mode,
            public_hostname=public_host,
            ts_hostname=ts_short,
            ts_suffix=ts_suffix,
            category=category,
        )
    return {
        "app": app_name,
        "by_env": rows,
        "updated_at": _now(),
    }


def apply_observed(
    row: Dict[str, Any],
    *,
    ingress_hosts: Optional[List[str]] = None,
    ts: Optional[Dict[str, Any]] = None,
    http_probe: Optional[Dict[str, Any]] = None,
    ts_device_listed: Optional[bool] = None,
    cf_ok: Optional[bool] = None,
) -> Dict[str, Any]:
    """Merge observed facts and compute status: validated | pending | drift | failed."""
    desired = dict(row.get("desired") or {})
    mode = _mode(desired.get("mode"))
    observed = dict(row.get("observed") or {})
    if ingress_hosts is not None:
        observed["ingress_hosts"] = list(ingress_hosts)
    if ts is not None:
        observed["ts"] = ts
    if http_probe is not None:
        observed["http"] = http_probe
    if ts_device_listed is not None:
        observed["ts_device_listed"] = ts_device_listed
    if cf_ok is not None:
        observed["cf_ok"] = cf_ok
    observed["checked_at"] = _now()

    expect_public = (desired.get("public_hostname") or "").lower()
    hosts = [h.lower() for h in (observed.get("ingress_hosts") or [])]
    ts_info = observed.get("ts") or {}
    http = observed.get("http") or {}

    status = "pending"
    errors: List[str] = []

    if mode in ("public", "both"):
        if expect_public and expect_public not in hosts:
            # Wrong host present (e.g. prod- prefixed) = drift; none = pending Argo
            if hosts:
                status = "drift"
                errors.append(
                    f"ingress hosts {hosts} != canonical public host {expect_public}"
                )
            else:
                status = "pending"
                errors.append("waiting for Ingress")
        elif http.get("ok"):
            status = "validated"
        elif http.get("status_code"):
            status = "pending"
            errors.append(f"public HTTP {http.get('status_code')}")
        else:
            status = "pending"
            errors.append(http.get("detail") or "waiting public HTTP")

        if mode == "both":
            if not ts_info.get("ready") or not observed.get("ts_device_listed"):
                if status == "validated":
                    status = "pending"
                errors.append("waiting Tailscale half of both")

    elif mode == "tailscale":
        if expect_public and expect_public in hosts:
            status = "drift"
            errors.append(f"public Ingress still present for {expect_public}")
        elif ts_info.get("ready") and observed.get("ts_device_listed"):
            status = "validated"
        elif not ts_info.get("exists"):
            status = "pending"
            errors.append("waiting TS Service")
        else:
            status = "pending"
            errors.append("waiting TailscaleProxyReady + device")

    elif mode == "off":
        if hosts or ts_info.get("exists"):
            status = "drift" if hosts else "pending"
            if hosts:
                errors.append(f"Ingress still present: {hosts}")
        else:
            status = "validated"

    elif mode in ("internal", "lan"):
        # No public Ingress expected
        if expect_public and expect_public in hosts:
            status = "drift"
            errors.append("public Ingress present but mode is not public")
        else:
            status = "validated"

    else:
        status = "pending"

    row = dict(row)
    row["observed"] = observed
    row["status"] = status
    row["last_error"] = "; ".join(errors) if errors else None
    row["updated_at"] = _now()
    return row


def summarize_inventory(inventory: Dict[str, Any]) -> Dict[str, Any]:
    by_env = inventory.get("by_env") or {}
    statuses = {env: (row or {}).get("status") for env, row in by_env.items()}
    drift = [env for env, st in statuses.items() if st == "drift"]
    pending = [env for env, st in statuses.items() if st == "pending"]
    failed = [env for env, st in statuses.items() if st == "failed"]
    validated = all(
        st == "validated" for st in statuses.values()
    ) if statuses else False
    return {
        "validated": validated and not drift and not failed,
        "drift": drift,
        "pending": pending,
        "failed": failed,
        "statuses": statuses,
    }
