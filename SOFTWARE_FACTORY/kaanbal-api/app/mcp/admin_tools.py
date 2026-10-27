"""
Herramientas de administración del MCP
======================================

Identidad y capacidades del token, versiones, datos, gobierno del inventario y
lo irreversible. Igual que el resto (tools.py): cada una llama a la REST con la
credencial de quien preguntó, así que permisos, alcance y bitácora son los de
siempre. Aquí solo se valida la forma de los argumentos y se resume la respuesta.

`context` lo arma el router por petición: la URL con que llegó el agente (para
decirle a qué instancia le habla) y las capacidades de autonomía descubiertas.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

from app.mcp import catalog
from app.mcp.protocol import ToolError
from app.services import autonomy_catalog, plans, platform_audit
from app.services.diagnosis import mask

HANDLED = frozenset({
    "whoami", "platform_capabilities", "invoke_platform_tool",
    "list_revisions", "pipeline_logs", "app_metrics", "check_urls", "wait_for_deploy", "audit_platform",
    "list_secret_requests", "restart_app", "request_secret", "rollback_app", "promote_app",
    "list_backups", "backup_database", "restore_database", "query_database",
    "set_app_group", "set_display_name", "delete_app",
})

DATABASE_TEMPLATES = ("postgres", "mongodb")
DELETE_BACKUP_HOURS = 24
# Capacidades de autonomía → interruptor de la política que las enciende.
FEATURES = {
    "execute_app_command": "runtime", "execute_node_command": "host", "merge_app_pr": "merge",
    "open_app_workspace": "workspace", "open_core_workspace": "workspace", "initialize_workspace": "workspace",
    "workspace_files": "workspace", "write_workspace_file": "workspace", "workspace_diff": "workspace",
    "run_workspace_command": "workspace", "publish_workspace_pr": "workspace", "close_workspace": "workspace",
    "get_workspace": "workspace", "open_repo_workspace": "workspace", "push_workspace": "workspace",
}
# Estas dependen de una concesión por app, nodo o core; las de repos personales, de la cuenta GitHub de la persona.
NEEDS_GRANT = {"execute_app_command", "execute_node_command", "merge_app_pr", "open_app_workspace", "open_core_workspace"}
NEEDS_APPROVAL = {"execute_app_command", "execute_node_command", "merge_app_pr", "platform_upgrade"}


async def _optional(client: Any, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Lo que el token pueda ver; None si no tiene permiso o no existe."""
    try:
        return await client.get(path, params)
    except ToolError:
        return None


# ── Identidad y capacidades ──────────────────────────────────────────────
async def _whoami(client: Any, context: Mapping[str, Any]) -> Dict[str, Any]:
    me = await client.get("/security/me")
    version = await _optional(client, "/core/version")
    domains = await _optional(client, "/domains") or []
    access = await _optional(client, "/autonomy/access")
    default = next((d.get("fqdn") for d in domains if d.get("is_default")), None)
    api_url = str(context.get("api_url") or "").rstrip("/") or None
    return {
        "instance": {
            "api_url": api_url,
            "mcp_url": f"{api_url}/mcp" if api_url else None,
            "default_domain": default,
            "domains": sorted(d.get("fqdn") for d in domains if d.get("fqdn")),
            "version": (version or {}).get("version") if isinstance(version, dict) else None,
            "upstream": (version or {}).get("upstream") if isinstance(version, dict) else None,
        },
        "account": {
            "username": me.get("username"), "roles": me.get("roles"), "superadmin": me.get("superadmin"),
            "via_token": me.get("via_token"), "token": me.get("token_name"), "elevated": me.get("elevated"),
            "permissions": len(me.get("permissions") or []),
        },
        "autonomy": access or "Este token no tiene autonomy.tools.view: no usa capacidades de autonomía.",
        "hint": "platform_capabilities dice qué herramientas puede usar este token y qué le falta a las demás.",
    }


def _tool_row(tool: Mapping[str, Any], permissions: set, elevated: bool, approval_on: bool) -> Dict[str, Any]:
    missing = []
    if tool.get("permission") and tool["permission"] not in permissions:
        missing.append(f"permiso {tool['permission']}")
    if tool.get("elevated") and not elevated:
        missing.append("token crítico")
    annotations = tool.get("annotations") or {}
    kind = ("consulta" if annotations.get("readOnlyHint") else
            "crítica" if tool.get("approval") else "plan" if tool.get("plan_first") else "acción")
    row = {"name": tool["name"], "group": tool["group"], "kind": kind, "permission": tool.get("permission"),
           "available": not missing}
    if missing:
        row["missing"] = missing
    if tool.get("approval") and approval_on:
        row["human_approval"] = True
    return row


def _capability_row(spec: Mapping[str, Any], permissions: set, elevated: bool,
                    access: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    missing = [f"permiso {p}" for p in [spec["permission"], *spec.get("extra_permissions", [])] if p and p not in permissions]
    if spec.get("elevated") and not elevated:
        missing.append("token crítico")
    feature = FEATURES.get(spec["name"])
    if feature and access is not None:
        if not (access.get("features") or {}).get(feature):
            missing.append(f"la política no enciende '{feature}'")
        elif (spec["name"] in NEEDS_GRANT and not access.get("grants")
              and not (access.get("elevated_tokens_bypass_grants") and elevated)):
            missing.append("sin concesión vigente en la política")
    kind = "consulta" if spec["method"] == "GET" else ("crítica" if spec.get("elevated") else "acción")
    row = {"name": spec["name"], "group": "autonomía", "kind": kind, "permission": spec["permission"],
           "available": not missing}
    if missing:
        row["missing"] = missing
    if spec["name"] in NEEDS_APPROVAL and (access or {}).get("approval_required", True):
        row["human_approval"] = True
    return row


async def _capabilities(client: Any, args: Mapping[str, Any]) -> Dict[str, Any]:
    me = await client.get("/security/me")
    permissions = set(me.get("permissions") or [])
    elevated = bool(me.get("elevated")) or not me.get("via_token")
    access = await _optional(client, "/autonomy/access") if "autonomy.tools.view" in permissions else None
    approval_on = bool(me.get("via_token")) and (access or {}).get("approval_required", True)
    rows = [_tool_row(tool, permissions, elevated, approval_on) for tool in catalog.TOOLS]
    rows += [_capability_row(spec, permissions, elevated, access) for spec in autonomy_catalog.TOOLS
             if spec["name"] not in catalog.TOOLS_BY_NAME]
    if args.get("only_available"):
        rows = [row for row in rows if row["available"]]
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    return {
        "token": me.get("token_name"), "elevated": bool(me.get("elevated")),
        "available": sum(1 for row in rows if row["available"]), "total": len(rows), "by_kind": counts,
        "legend": {"consulta": "solo lee", "plan": "muestra el plan y aplica con plan_id",
                   "acción": "actúa directo: confirma con la persona", "crítica": "irreversible: token crítico y "
                   "aprobación humana (approval_id)"},
        "tools": rows,
    }


async def _invoke(client: Any, args: Mapping[str, Any], context: Mapping[str, Any]) -> Any:
    from app.mcp.tools import call_discovered_tool

    discovered = context.get("discovered") or {}
    name = str(args.get("tool") or "")
    spec = discovered.get(name)
    if spec is None:
        known = ", ".join(sorted(discovered)) or "ninguna (el token no tiene autonomy.tools.view)"
        raise ToolError(f"'{name}' no es una capacidad disponible para este token. Disponibles: {known}.")
    arguments = args.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ToolError("arguments debe ser un objeto.")
    return await call_discovered_tool(client, spec, arguments)


# ── Entender ─────────────────────────────────────────────────────────────
def _trim(text: str, limit: int) -> str:
    text = "\n".join(mask(line) for line in (text or "").splitlines())
    return text if len(text) <= limit else "…" + text[-limit:]


async def _pipeline_logs(client: Any, app: str, args: Mapping[str, Any]) -> Dict[str, Any]:
    limit = args.get("max_chars", 6000)
    history = args.get("history", 5)
    for key, value, low, high in (("max_chars", limit, 500, 20000), ("history", history, 0, 10)):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ToolError(f"{key} va de {low} a {high}.")
    logs = await client.get(f"/apps/{app}/pipeline/logs")
    if isinstance(logs, dict) and logs.get("error"):
        return {"app": app, "error": mask(str(logs["error"]))}
    steps = []
    for step in (logs or {}).get("steps") or []:
        row = {key: step.get(key) for key in ("name", "result", "state", "duration_in_seconds") if step.get(key) is not None}
        if step.get("result") not in ("SUCCESSFUL", "success", "COMPLETED") and step.get("logs"):
            row["log_tail"] = _trim(step["logs"], limit)
        steps.append(row)
    result = {"app": app, "pipeline": (logs or {}).get("pipeline_info"), "steps": steps}
    if history:
        past = await _optional(client, f"/apps/{app}/pipeline/history", {"limit": history})
        result["history"] = (past or {}).get("pipelines")
    failed = [step["name"] for step in steps if "log_tail" in step]
    result["hint"] = (f"Falló en: {', '.join(failed)}. El final de su log está en log_tail." if failed
                      else "Ningún paso con error en el último pipeline.")
    return result


async def _wait(client: Any, app: str, args: Mapping[str, Any]) -> Dict[str, Any]:
    from app.mcp.tools import call_tool

    timeout = args.get("timeout_seconds", 90)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 10 <= timeout <= 150:
        raise ToolError("timeout_seconds va de 10 a 150.")
    deadline = time.monotonic() + timeout
    while True:
        status = await call_tool(client, "deploy_status", {"name": app})
        if not str(status.get("hint", "")).startswith("Sigue en curso") or time.monotonic() >= deadline:
            status["waited_until_done"] = not str(status.get("hint", "")).startswith("Sigue en curso")
            return status
        await asyncio.sleep(min(5.0, max(0.0, deadline - time.monotonic())))


def _health_by_app(apps: List[Mapping[str, Any]], argocd: Any) -> Dict[str, Optional[str]]:
    rank = {"Healthy": 0, "Progressing": 1, "Suspended": 2, "Missing": 3, "Unknown": 3, "Degraded": 4}
    by_name = {row.get("name"): row.get("health") for row in ((argocd or {}).get("apps") or [])}
    result: Dict[str, Optional[str]] = {}
    for app in apps:
        names = [app["name"]] + [f"{app['name']}-{env}" for env in app.get("environments") or []]
        states = [by_name[n] for n in names if n in by_name]
        result[app["name"]] = max(states, key=lambda s: rank.get(s, 3)) if states else None
    return result


async def _audit(client: Any, args: Mapping[str, Any]) -> Dict[str, Any]:
    from app.mcp.tools import call_tool

    apps = (await call_tool(client, "list_apps", {}))["apps"]
    answer = await _optional(client, "/links")
    links = answer or []
    notes = [] if answer is not None else ["Sin links.links.view: no se revisan los vínculos."]
    health = None
    if args.get("include_health", True):
        argocd = await _optional(client, "/apps/argocd/all")
        health = _health_by_app(apps, argocd) if argocd and argocd.get("connected", True) else None
    backups = None
    if args.get("include_backups", True):
        backups = {}
        for app in apps:
            if app.get("template") not in DATABASE_TEMPLATES:
                continue
            answer = await _optional(client, f"/apps/{app['name']}/backups")
            if answer is None:
                backups = None
                notes.append("Sin data.backups.view: no se revisan los respaldos.")
                break
            done = [op for op in answer.get("operations") or [] if op.get("kind") == "backup" and op.get("state") == "succeeded"]
            backups[app["name"]] = done[0].get("created_at") if done else None
    # Qué bases usa cada app, por los nombres de sus variables (nunca valores).
    variable_names: Optional[Dict[str, List[str]]] = {}
    for app in apps:
        if app.get("template") in DATABASE_TEMPLATES:
            continue
        env = "prod" if "prod" in (app.get("environments") or ["prod"]) else (app.get("environments") or ["prod"])[0]
        answer_names = await _optional(client, f"/apps/{app['name']}/env-vars", {"env": env})
        if answer_names is None:
            variable_names = None
            notes.append("Sin apps.apps.diagnose: no se revisan las variables de las apps.")
            break
        variable_names[app["name"]] = list(answer_names.get("names") or [])
    report = platform_audit.audit(apps, [{"from_app": l.get("from_app"), "to_app": l.get("to_app")} for l in links],
                                  health=health, backups=backups, variable_names=variable_names)
    if notes:
        report["notes"] = notes
    return report


# ── Lo irreversible ──────────────────────────────────────────────────────
def _recent(created: Any, hours: int) -> bool:
    try:
        when = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when <= timedelta(hours=hours)


async def _delete_app(client: Any, app: str, args: Mapping[str, Any]) -> Dict[str, Any]:
    from app.mcp.tools import _approval_id, _plan_id

    doc = await client.get(f"/apps/{app}")
    consumers = await _optional(client, "/links", {"to_app": app}) or []
    uses = await _optional(client, "/links", {"from_app": app}) or []
    is_database = str(doc.get("template") or "") in DATABASE_TEMPLATES
    without_backup = bool(args.get("without_backup"))
    backup = None
    if is_database:
        answer = await _optional(client, f"/apps/{app}/backups") or {}
        done = [op for op in answer.get("operations") or [] if op.get("kind") == "backup" and op.get("state") == "succeeded"]
        backup = done[0] if done else None
        if not without_backup and not (backup and _recent(backup.get("created_at"), DELETE_BACKUP_HOURS)):
            raise ToolError(f"{app} es una base y no tiene un respaldo de las últimas {DELETE_BACKUP_HOURS} h. "
                            "Corre backup_database y espera a que termine (list_backups), o pide el plan con "
                            "without_backup=true si de verdad no hay nada que conservar.")
    domain = doc.get("domain") or {}
    plan = {
        "action": "delete_app", "app": app, "template": doc.get("template"),
        "environments": doc.get("environments") or ["prod"], "urls": domain.get("urls") or {},
        "is_homepage": bool(doc.get("is_root_domain")), "repository": doc.get("repo_url"),
        "used_by": sorted({link.get("from_app") for link in consumers if link.get("from_app")}),
        "uses": sorted({link.get("to_app") for link in uses if link.get("to_app")}),
        "backup": {key: backup.get(key) for key in ("id", "env", "created_at", "size")} if backup else None,
        "without_backup": without_backup,
        "effects": ["Se borran el repositorio, los secretos en Vault, los overlays de infra-gitops y los despliegues.",
                    "Las URLs dejan de responder y el nombre queda libre.",
                    "Las apps que la usan pierden la conexión (sus variables apuntan a algo que ya no existe)."],
    }
    pid = plans.plan_id("delete_app", plan)
    given = _plan_id(dict(args))
    if given is None:
        return {"applied": False, "plan": plan, "plan_id": pid,
                "next": ("Nada se borró. Muéstrale el plan a la persona; si lo aprueba, repite con plan_id=\""
                         f"{pid}\". Desde un token la API pedirá además aprobación humana (approval_id).")}
    if given != pid:
        raise ToolError("El plan cambió desde que lo viste (dependencias, respaldo o estado). Pide el plan de nuevo.")
    params = {}
    approval = _approval_id(dict(args))
    if approval:
        params["approval_id"] = approval
    result = await client.request("DELETE", f"/apps/{doc['_id']}", params=params)
    return {"applied": True, "app": app, "cleanup": result.get("cleanup"), "message": result.get("message")}


# ── Despacho ─────────────────────────────────────────────────────────────
async def call(client: Any, name: str, args: Dict[str, Any], context: Mapping[str, Any]) -> Any:
    from app.mcp.tools import _app, _env, _plan_or_apply

    if name == "whoami":
        return await _whoami(client, context)
    if name == "platform_capabilities":
        return await _capabilities(client, args)
    if name == "invoke_platform_tool":
        return await _invoke(client, args, context)
    if name == "audit_platform":
        return await _audit(client, args)

    app = _app(args)
    if name == "list_revisions":
        return await client.get(f"/apps/{app}/revisions", {"env": _env(args)})
    if name == "pipeline_logs":
        return await _pipeline_logs(client, app, args)
    if name == "app_metrics":
        return await client.get(f"/apps/{app}/metrics", {"env": _env(args)})
    if name == "check_urls":
        return await client.get(f"/apps/{app}/probe")
    if name == "wait_for_deploy":
        return await _wait(client, app, args)
    if name == "list_secret_requests":
        return await client.get(f"/apps/{app}/secret-requests")

    if name == "restart_app":
        return await client.post(f"/apps/{app}/environments/{_env(args)}/restart")
    if name == "request_secret":
        body = {key: args.get(key) for key in ("variable", "reason", "environments") if args.get(key) is not None}
        return await client.post(f"/apps/{app}/secret-requests", body)
    if name == "rollback_app":
        env = _env(args)
        applied, result = await _plan_or_apply(client, "POST", f"/apps/{app}/environments/{env}/rollback", args,
                                               {"tag": str(args.get("tag") or "")})
        return result if not applied else {**result, "next": f"Sigue el despliegue con wait_for_deploy(name='{app}')."}
    if name == "promote_app":
        body = {"from_env": str(args.get("from_env") or "staging"), "to_env": str(args.get("to_env") or "prod")}
        applied, result = await _plan_or_apply(client, "POST", f"/apps/{app}/promote", args, body)
        return result if not applied else {**result, "next": f"Sigue el despliegue con wait_for_deploy(name='{app}')."}

    if name == "list_backups":
        return await client.get(f"/apps/{app}/backups")
    if name == "backup_database":
        return await client.request("POST", f"/apps/{app}/backups", params={"env": _env(args)}, json={})
    if name == "restore_database":
        backup_id = str(args.get("backup_id") or "")
        if not backup_id.isalnum() or len(backup_id) > 40:
            raise ToolError("backup_id no es válido: usa el id que muestra list_backups.")
        applied, result = await _plan_or_apply(client, "POST", f"/apps/{app}/backups/{backup_id}/restore", args,
                                               {}, params={"env": _env(args)})
        return result
    if name == "query_database":
        body = {key: args[key] for key in ("sql", "operation", "database", "collection", "filter", "projection",
                                           "sort", "limit") if args.get(key) is not None}
        return await client.post(f"/apps/{app}/query", {**body, "env": _env(args)})

    if name == "set_app_group":
        group = str(args.get("group") or "").strip()
        return await client.request("PATCH", f"/apps/{app}/group", json={"app_group": group or None})
    if name == "set_display_name":
        return await client.request("PATCH", f"/apps/{app}/display-name",
                                    json={"display_name": str(args.get("display_name") or "")})
    if name == "delete_app":
        return await _delete_app(client, app, args)
    raise ToolError(f"Herramienta desconocida: {name}")
