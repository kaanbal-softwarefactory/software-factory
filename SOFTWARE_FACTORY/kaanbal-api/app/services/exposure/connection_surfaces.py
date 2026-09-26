"""Build multi-surface connection URLs (Fase 3).

Surfaces describe how a human/tool reaches an app per environment:
  - public_url / editor_url / webhook_url / mcp_url / ws_url
  - tailscale_url / cluster_url / lan_url
  - tcp ports (EMQX mqtt/ws)

Catalog may declare:
  exposure.surfaces = {
    "editor":   { "via": "private", "path": "/" },
    "webhook":  { "via": "public",  "path": "/webhook/" },
    "mcp":      { "via": "public",  "path": "/mcp/" },
    "ws":       { "via": "public",  "path": "/ws" }
  }
Defaults are inferred from category + public_paths + private_env_vars.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _public_base(hostname: str) -> str:
    return f"https://{hostname}" if hostname else ""


def _ts_base(hostname: str, suffix: str) -> str:
    if not hostname:
        return ""
    if hostname.endswith(".ts.net"):
        return f"http://{hostname}"
    return f"http://{hostname}.{suffix}" if suffix else f"http://{hostname}"


def infer_surfaces(spec: Any = None, category: str = "") -> Dict[str, Dict[str, str]]:
    """Return surface map from template spec or category defaults."""
    exposure = {}
    if spec is not None:
        data = getattr(spec, "_data", None) or {}
        exposure = data.get("exposure") or {}
        if exposure.get("surfaces"):
            return dict(exposure["surfaces"])
        category = category or getattr(spec, "category", "") or data.get("category", "")

    public_paths = []
    if spec is not None and hasattr(spec, "public_paths"):
        public_paths = list(spec.public_paths or [])

    surfaces: Dict[str, Dict[str, str]] = {}
    cat = (category or "").lower()

    if cat == "workflow" or public_paths:
        surfaces["editor"] = {"via": "private", "path": "/", "label": "Editor UI"}
        surfaces["webhook"] = {"via": "public", "path": "/webhook/", "label": "Webhooks"}
        surfaces["mcp"] = {"via": "public", "path": "/mcp/", "label": "MCP server"}
    elif cat == "frontend":
        surfaces["ui"] = {"via": "auto", "path": "/", "label": "UI"}
    elif cat == "backend":
        surfaces["api"] = {"via": "auto", "path": "/", "label": "API"}
        surfaces["ws"] = {"via": "auto", "path": "/ws", "label": "WebSocket"}
        surfaces["health"] = {"via": "auto", "path": "/health", "label": "Health"}
    elif cat == "iot":
        surfaces["dashboard"] = {"via": "auto", "path": "/", "label": "Dashboard"}
        surfaces["mqtt"] = {"via": "tcp", "path": "", "label": "MQTT"}
        surfaces["ws"] = {"via": "tcp", "path": "", "label": "MQTT over WS"}
    else:
        surfaces["primary"] = {"via": "auto", "path": "/", "label": "Primary"}

    # Merge explicit catalog surfaces on top
    if exposure.get("surfaces"):
        surfaces.update(exposure["surfaces"])
    return surfaces


def build_env_surfaces(
    *,
    mode: str,
    public_hostname: str,
    ts_hostname: str,
    ts_suffix: str,
    app_name: str,
    env: str,
    surfaces: Optional[Dict[str, Dict[str, str]]] = None,
    category: str = "",
    tcp_ports: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Resolve concrete URLs for one env given exposure mode."""
    mode = (mode or "internal").lower()
    surfaces = surfaces or infer_surfaces(category=category)
    public = _public_base(public_hostname)
    private = _ts_base(ts_hostname, ts_suffix)
    cluster = f"http://{app_name}.{env}.svc.cluster.local"

    def pick(via: str, path: str = "/") -> Optional[str]:
        path = path or "/"
        if via == "public":
            base = public if mode in ("public", "both") else None
        elif via == "private":
            base = private if mode in ("tailscale", "both") else (
                public if mode == "public" else private
            )
        elif via == "cluster":
            base = cluster
        elif via == "tcp":
            return None  # filled below from tcp_ports
        else:  # auto
            if mode in ("public", "both"):
                base = public
            elif mode == "tailscale":
                base = private
            elif mode == "lan":
                base = None
            elif mode == "off":
                return None
            else:
                base = cluster
        if not base:
            if mode == "internal":
                base = cluster
            else:
                return None
        if path == "/":
            return base
        return base.rstrip("/") + (path if path.startswith("/") else f"/{path}")

    out: Dict[str, Any] = {
        "mode": mode,
        "public_url": public if mode in ("public", "both") else None,
        "tailscale_url": private if mode in ("tailscale", "both") else None,
        "cluster_url": cluster,
        "surfaces": {},
    }

    for name, meta in surfaces.items():
        via = (meta.get("via") or "auto").lower()
        path = meta.get("path") or "/"
        url = pick(via, path)
        entry = {
            "label": meta.get("label") or name,
            "via": via,
            "path": path,
            "url": url,
        }
        out["surfaces"][name] = entry
        # Convenience aliases for known names
        if name in ("editor", "ui") and url:
            out["editor_url"] = url
        if name == "webhook" and url:
            out["webhook_url"] = url
        if name == "mcp" and url:
            out["mcp_url"] = url
        if name == "api" and url:
            out["api_url"] = url
        if name == "ws" and url and via != "tcp":
            out["ws_url"] = url
        if name == "health" and url:
            out["health_url"] = url
        if name == "dashboard" and url:
            out["dashboard_url"] = url

    # EMQX / TCP surfaces — L4 always via Tailscale hostname when mode allows reachability.
    # Dashboard stays L7 (HTTP Ingress / MagicDNS) via surfaces.dashboard; mqtt/ws are L4.
    if tcp_ports and mode in ("tailscale", "both", "public", "lan"):
        tcp_out = {}
        for tp in tcp_ports:
            pname = (tp.get("name") or "tcp").lower()
            port = tp.get("port")
            # Prefer MagicDNS L4 host even if UI mode is public (broker rarely on CF)
            host = f"{env}-{app_name}-{pname}.{ts_suffix}" if ts_suffix else f"{env}-{app_name}-{pname}"
            if pname == "mqtt":
                url = f"mqtt://{host}:{port or 1883}"
                layer = "L4"
            elif pname in ("ws", "mqtt-ws", "websocket"):
                url = f"ws://{host}:{port or 8083}"
                layer = "L4"
            else:
                url = f"tcp://{host}:{port}" if port else f"tcp://{host}"
                layer = "L4"
            tcp_out[pname] = {
                "port": port,
                "host": host,
                "url": url,
                "layer": layer,
                "transport": "tailscale-tcp",
            }
            if pname in out["surfaces"]:
                out["surfaces"][pname]["url"] = url
                out["surfaces"][pname]["via"] = "tcp"
                out["surfaces"][pname]["layer"] = layer
            else:
                out["surfaces"][pname] = {
                    "label": pname,
                    "via": "tcp",
                    "path": "",
                    "url": url,
                    "layer": layer,
                }
        out["tcp"] = tcp_out

    # Mark L7 HTTP surfaces explicitly (dashboard / editor / ui / api)
    for l7_name in ("dashboard", "editor", "ui", "api", "webhook", "mcp", "health", "primary"):
        if l7_name in out["surfaces"] and out["surfaces"][l7_name].get("via") != "tcp":
            out["surfaces"][l7_name]["layer"] = "L7"

    if mode == "off":
        out["status"] = "off"
        for s in out["surfaces"].values():
            s["url"] = None
    else:
        out["status"] = "active"

    return out
