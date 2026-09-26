"""In-cluster K8s + HTTP probes for exposure validation (no kubectl binary)."""
from __future__ import annotations

import logging
import os
import ssl
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SA_TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"
SA_CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
K8S_BASE = "https://kubernetes.default.svc"


def in_cluster() -> bool:
    return os.path.exists(SA_TOKEN)


def _httpx():
    import httpx
    return httpx


def _sa_headers_and_ssl() -> Tuple[Dict[str, str], Any]:
    with open(SA_TOKEN) as f:
        token = f.read().strip()
    ssl_ctx = (
        ssl.create_default_context(cafile=SA_CA) if os.path.exists(SA_CA) else False
    )
    return {"Authorization": f"Bearer {token}"}, ssl_ctx


async def k8s_get(path: str, timeout: float = 15.0) -> Tuple[int, Any]:
    """GET path on kubernetes.default.svc. Returns (status_code, json_or_none)."""
    if not in_cluster():
        return 0, None
    httpx = _httpx()
    headers, ssl_ctx = _sa_headers_and_ssl()
    async with httpx.AsyncClient(verify=ssl_ctx, timeout=timeout) as client:
        resp = await client.get(f"{K8S_BASE}{path}", headers=headers)
        try:
            body = resp.json()
        except Exception:
            body = None
        return resp.status_code, body


async def get_ingress_hosts(namespace: str, app_name: str) -> List[str]:
    """List Ingress rule hosts for app in namespace (name match or label app=)."""
    hosts: List[str] = []
    code, data = await k8s_get(f"/apis/networking.k8s.io/v1/namespaces/{namespace}/ingresses")
    if code != 200 or not data:
        return hosts
    for item in data.get("items") or []:
        meta = item.get("metadata") or {}
        labels = meta.get("labels") or {}
        name = meta.get("name") or ""
        if name != app_name and labels.get("app") != app_name:
            continue
        for rule in (item.get("spec") or {}).get("rules") or []:
            h = (rule.get("host") or "").strip().lower()
            if h:
                hosts.append(h)
    return hosts


async def get_ts_service_ready(namespace: str, app_name: str) -> Dict[str, Any]:
    """Return Tailscale Service presence + TailscaleProxyReady."""
    svc = f"{app_name}-ts"
    code, data = await k8s_get(f"/api/v1/namespaces/{namespace}/services/{svc}")
    if code == 404:
        return {"exists": False, "ready": False, "service": svc}
    if code != 200 or not data:
        return {"exists": False, "ready": False, "service": svc, "http": code}
    conditions = (data.get("status") or {}).get("conditions") or []
    ready = any(
        c.get("type") == "TailscaleProxyReady" and str(c.get("status")) == "True"
        for c in conditions
    )
    hostname = ((data.get("metadata") or {}).get("annotations") or {}).get(
        "tailscale.com/hostname"
    ) or ""
    return {
        "exists": True,
        "ready": ready,
        "service": svc,
        "hostname": hostname,
    }


async def wait_projection(
    *,
    app_name: str,
    env: str,
    mode: str,
    expected_public_host: str,
    attempts: int = 18,
) -> Dict[str, Any]:
    """Poll until Ingress / TS Service match desired mode (Argo race window)."""
    import asyncio

    mode = (mode or "").lower()
    want_public = mode in ("public", "both")
    want_ts = mode in ("tailscale", "both")
    expected = (expected_public_host or "").strip().lower()
    detail = "not in-cluster"
    last: Dict[str, Any] = {}

    if not in_cluster():
        return {
            "ok": True,
            "skipped": True,
            "detail": "outside cluster — projection wait skipped",
            "ingress_hosts": [],
            "ts": {},
        }

    for i in range(attempts):
        hosts = await get_ingress_hosts(env, app_name)
        ts = await get_ts_service_ready(env, app_name)
        last = {"ingress_hosts": hosts, "ts": ts}

        if want_public:
            public_ok = expected in hosts if expected else bool(hosts)
        else:
            # Leaving public: canonical host must be gone (Argo deleted Ingress)
            public_ok = expected not in hosts if expected else True

        # Tailscale: wait until ProxyReady; leaving VPN does not block on orphan SVC
        ts_ok = bool(ts.get("exists")) and bool(ts.get("ready")) if want_ts else True

        if public_ok and ts_ok:
            detail = (
                f"projection ok ingress={hosts} ts_ready={ts.get('ready')} "
                f"ts_exists={ts.get('exists')}"
            )
            return {"ok": True, "detail": detail, **last}

        detail = (
            f"waiting projection mode={mode} expect_host={expected} "
            f"hosts={hosts} ts_exists={ts.get('exists')} ts_ready={ts.get('ready')}"
        )
        await asyncio.sleep(min(2 + i, 8))

    return {"ok": False, "detail": detail or "projection timeout", **last}


async def probe_http_url(url: str, timeout: float = 12.0) -> Dict[str, Any]:
    """HTTP(S) GET probe against canonical URL. Follow redirects; accept 2xx/3xx."""
    if not url:
        return {"ok": False, "status_code": 0, "detail": "empty url"}
    httpx = _httpx()
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, verify=True
        ) as client:
            resp = await client.get(url)
        code = resp.status_code
        ok = 200 <= code < 400
        return {
            "ok": ok,
            "status_code": code,
            "detail": f"HTTP {code}",
            "url": url,
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("http probe failed %s: %s", url, exc)
        return {
            "ok": False,
            "status_code": 0,
            "detail": f"{type(exc).__name__}: {exc}",
            "url": url,
        }


async def wait_public_http(
    url: str, attempts: int = 12
) -> Dict[str, Any]:
    """Retry public HTTP until 2xx/3xx (CF/cert/Argo race)."""
    import asyncio

    last: Dict[str, Any] = {"ok": False, "detail": "no attempts", "url": url}
    for i in range(attempts):
        last = await probe_http_url(url)
        if last.get("ok"):
            return last
        await asyncio.sleep(min(2 + i, 8))
    return last
