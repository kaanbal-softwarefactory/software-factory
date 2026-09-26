"""Normalize multi-channel port exposure (EMQX Edge and multi-port apps).

Legacy shape (single mode string):
  { "prod": { "mqtt": "tailscale" } }

Edge shape (channels list):
  { "prod": { "mqtt": ["internal", "lan", "tailscale"] } }

Also accepts:
  { "prod": { "mqtt": { "channels": ["lan", "tailscale"], "enabled": true } } }
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

VALID_CHANNELS = frozenset({"internal", "lan", "tailscale", "public", "off"})

# Ports that must never get a public HTTP Ingress (raw MQTT TCP).
PUBLIC_FORBIDDEN_PORTS = frozenset({"mqtt", "mqtt_tls", "mqtt-tcp"})

# Ports that are L7/WebSocket-compatible for Cloudflare public exposure.
PUBLIC_ALLOWED_PORTS = frozenset({"ws", "websocket", "dashboard", "http", "main", "https"})

EDGE_PROFILE_CHANNELS: Dict[str, List[str]] = {
    "mqtt": ["internal", "lan", "tailscale"],
    "ws": ["internal", "lan", "tailscale", "public"],
    "websocket": ["internal", "lan", "tailscale", "public"],
    "dashboard": ["internal", "lan", "tailscale"],
    "mqtt_tls": [],
}


def normalize_channels(value: Any) -> List[str]:
    """Coerce a port exposure value into a deduplicated channel list."""
    if value is None:
        return []
    if isinstance(value, str):
        mode = value.strip().lower()
        if not mode or mode == "off":
            return []
        if mode == "both":
            return ["public", "tailscale"]
        if mode in VALID_CHANNELS:
            return [mode]
        return []
    if isinstance(value, dict):
        if value.get("enabled") is False:
            return []
        return normalize_channels(value.get("channels") or value.get("modes") or [])
    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        seen: Set[str] = set()
        for item in value:
            for ch in normalize_channels(item):
                if ch not in seen:
                    seen.add(ch)
                    out.append(ch)
        return out
    return []


def flatten_env_channels(env_ports: Dict[str, Any]) -> Set[str]:
    """All channels used by any port in one env matrix row."""
    found: Set[str] = set()
    for raw in (env_ports or {}).values():
        found.update(normalize_channels(raw))
    return found


def derive_env_mode(env_ports: Dict[str, Any]) -> str:
    """Collapse multi-channel matrix into legacy env-level exposure mode."""
    channels = flatten_env_channels(env_ports)
    if not channels:
        return "internal"
    has_public = "public" in channels
    has_ts = "tailscale" in channels
    has_lan = "lan" in channels
    if has_public and has_ts:
        return "both"
    if has_public:
        return "public"
    if has_ts:
        return "tailscale"
    if has_lan:
        return "lan"
    return "internal"


def sanitize_public_channels(port_name: str, channels: Iterable[str]) -> List[str]:
    """Drop public from MQTT TCP; keep public only on allowed surfaces."""
    name = (port_name or "").lower()
    out: List[str] = []
    for ch in channels:
        if ch != "public":
            out.append(ch)
            continue
        if name in PUBLIC_FORBIDDEN_PORTS:
            continue
        if name in PUBLIC_ALLOWED_PORTS or name.startswith("ws"):
            out.append(ch)
    return out


def apply_edge_profile(
    ports: Optional[List[dict]] = None,
    *,
    enable_lan: bool = True,
    enable_tailscale: bool = True,
    enable_public_ws: bool = True,
    enable_public_dashboard: bool = False,
) -> Dict[str, List[str]]:
    """Build per-port channels for the EMQX Edge profile."""
    result: Dict[str, List[str]] = {}
    port_names = [p.get("name") if isinstance(p, dict) else getattr(p, "name", None) for p in (ports or [])]
    port_names = [n for n in port_names if n]

    def filter_channels(base: List[str], port_name: str) -> List[str]:
        out = []
        for ch in base:
            if ch == "lan" and not enable_lan:
                continue
            if ch == "tailscale" and not enable_tailscale:
                continue
            if ch == "public":
                if port_name in ("ws", "websocket") and not enable_public_ws:
                    continue
                if port_name == "dashboard" and not enable_public_dashboard:
                    continue
            out.append(ch)
        return sanitize_public_channels(port_name, out)

    defaults = EDGE_PROFILE_CHANNELS
    names = port_names or list(defaults.keys())
    for name in names:
        base = list(defaults.get(name, ["internal"]))
        if name == "dashboard" and enable_public_dashboard and "public" not in base:
            base = base + ["public"]
        result[name] = filter_channels(base, name)
    return result


def public_ws_hostname(app_name: str, domain: str, env: str = "prod") -> str:
    """Canonical public WSS host: mqtt-{app}.{domain}."""
    if env == "prod":
        return f"mqtt-{app_name}.{domain}"
    return f"{env}-mqtt-{app_name}.{domain}"


def build_port_exposure_for_envs(
    environments: List[str],
    per_port_channels: Dict[str, List[str]],
) -> Dict[str, Dict[str, List[str]]]:
    """Expand a port→channels map across environments."""
    return {env: {k: list(v) for k, v in per_port_channels.items()} for env in environments}
