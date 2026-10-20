"""Cómo se conecta un agente a ESTA instalación.

La URL del MCP no se puede escribir en la documentación: cambia con el dominio de
cada célula. Tampoco basta con mirar la petición, porque la consola proxea
`/api/` con su propio Host y el `/mcp` no pasa por ahí: desde el navegador la
petición parece venir de la consola, no de la API.

Así que se resuelve de la fuente más fiel a la realidad del clúster a la menos:

1. el Ingress que de verdad publica la API (lo que responde en internet),
2. el nombre MagicDNS cuando la API vive solo en la VPN,
3. la convención `kaanbal-api.<dominio>` sobre el dominio de la instalación,
4. y, si no hay nada de eso, la URL con la que llegó la petición.

Cada respuesta dice de dónde salió (`source`) y hasta dónde llega (`reach`),
para que la consola no prometa una URL pública que nadie puede abrir.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.mcp import catalog
from app.version import VERSION

INGRESS_NAME = "kaanbal-api"
NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
DEFAULT_NAMESPACE = "kaanbal"

# Lo que ve quien abre la página: de dónde salió la URL y a quién le sirve.
SOURCE_LABELS = {
    "ingress": "del Ingress que publica la API en este clúster",
    "tailnet": "del nombre de la VPN: la API no está publicada en internet",
    "domain": "de la convención kaanbal-api.<dominio> de esta instalación",
    "request": "de la dirección con la que llegó esta petición",
}

REACH_LABELS = {
    "internet": "Cualquier agente con el token puede conectarse.",
    "vpn": "Solo desde la VPN de la célula: el agente tiene que estar en el tailnet.",
    "unknown": "No se pudo confirmar desde dónde responde; pruébala antes de repartirla.",
}


def _namespace() -> str:
    try:
        with open(NAMESPACE_FILE, encoding="utf-8") as handle:
            return handle.read().strip() or DEFAULT_NAMESPACE
    except OSError:
        return DEFAULT_NAMESPACE


def ingress_host() -> Optional[str]:
    """El host del Ingress de la API, o None si no hay (modo tailnet) o no se puede leer."""
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        ingress = client.NetworkingV1Api().read_namespaced_ingress(INGRESS_NAME, _namespace())
        for rule in ingress.spec.rules or []:
            if rule.host:
                return str(rule.host).strip()
    except Exception:
        return None
    return None


def _clean(value: Any) -> str:
    return str(value or "").strip().strip("/")


def resolve_api_url(config: Dict[str, Any], request_base: str = "") -> Tuple[str, str, str]:
    """Devuelve (url, source, reach) de la API pública de esta instalación."""
    host = ingress_host()
    if host:
        return f"https://{host}", "ingress", "internet"

    domain = _clean(config.get("domain")).lower()
    tailnet = _clean(config.get("tailscale_dns_suffix")).lower()
    if tailnet:
        return f"https://{INGRESS_NAME}.{tailnet}", "tailnet", "vpn"
    if domain:
        return f"https://{INGRESS_NAME}.{domain}", "domain", "unknown"

    base = _clean(request_base)
    if base:
        return base, "request", "unknown"
    return "", "request", "unknown"


def _clients(mcp_url: str, api_url: str) -> List[Dict[str, str]]:
    """Lo que hay que pegar en cada cliente, ya con la URL de esta célula."""
    token = "kbl_TU_TOKEN"
    return [
        {
            "id": "claude-code",
            "name": "Claude Code",
            "language": "bash",
            "note": "Un comando y queda registrado para este equipo.",
            "snippet": (
                f'claude mcp add --transport http kaanbal {mcp_url} '
                f'--header "Authorization: Bearer {token}"'
            ),
        },
        {
            "id": "http",
            "name": "Cursor, Codex y otros clientes HTTP",
            "language": "json",
            "note": "En Cursor va en ~/.cursor/mcp.json; los demás usan la misma forma.",
            "snippet": (
                '{\n'
                '  "mcpServers": {\n'
                '    "kaanbal": {\n'
                f'      "url": "{mcp_url}",\n'
                f'      "headers": {{ "Authorization": "Bearer {token}" }}\n'
                '    }\n'
                '  }\n'
                '}'
            ),
        },
        {
            "id": "stdio",
            "name": "Clientes que solo hablan stdio",
            "language": "json",
            "note": "Usa el puente kaanbal-mcp, que reenvía cada mensaje a /mcp. Solo necesita httpx.",
            "snippet": (
                '{\n'
                '  "mcpServers": {\n'
                '    "kaanbal": {\n'
                '      "command": "python",\n'
                '      "args": ["-m", "kaanbal_mcp"],\n'
                '      "cwd": "<ruta a SOFTWARE_FACTORY/kaanbal-mcp>",\n'
                f'      "env": {{ "KAANBAL_URL": "{api_url}", "KAANBAL_TOKEN": "{token}" }}\n'
                '    }\n'
                '  }\n'
                '}'
            ),
        },
    ]


def _tools_summary() -> Dict[str, Any]:
    groups: Dict[str, int] = {}
    elevated = 0
    plan_first = 0
    for tool in catalog.TOOLS:
        groups[tool["group"]] = groups.get(tool["group"], 0) + 1
        if tool.get("elevated"):
            elevated += 1
        if tool.get("plan_first"):
            plan_first += 1
    return {
        "total": len(catalog.TOOLS),
        "by_group": groups,
        "elevated": elevated,
        "plan_first": plan_first,
    }


def info(config: Dict[str, Any], request_base: str = "") -> Dict[str, Any]:
    """Todo lo que la consola necesita para enseñar cómo conectarse aquí."""
    api_url, source, reach = resolve_api_url(config, request_base)
    mcp_url = f"{api_url}/mcp" if api_url else ""
    return {
        "version": VERSION,
        "domain": _clean(config.get("domain")).lower(),
        "api_url": api_url,
        "mcp_url": mcp_url,
        "source": source,
        "source_label": SOURCE_LABELS.get(source, ""),
        "reach": reach,
        "reach_label": REACH_LABELS.get(reach, ""),
        "docs": {
            "api": f"{api_url}/docs" if api_url else "",
            "api_alternative": f"{api_url}/redoc" if api_url else "",
            "openapi": f"{api_url}/openapi.json" if api_url else "",
        },
        "auth": {
            "header": "Authorization: Bearer <token>",
            "where": "Acceso → Tokens",
            "note": (
                "Cada agente usa su propio token: así se revoca uno sin tocar a los demás y la "
                "actividad queda a nombre de quien la pidió. Las acciones irreversibles piden "
                "además un token crítico y la aprobación de una persona en Acceso → Solicitudes."
            ),
        },
        "clients": _clients(mcp_url, api_url),
        "tools": _tools_summary(),
    }
