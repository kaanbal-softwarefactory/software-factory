"""
Diagnóstico de una app, en lenguaje simple
=========================================

Responde "¿por qué no funciona mi app?" para alguien que no lee tracebacks.
Reúne lo que hace falta —estado del despliegue y de sus versiones, pods,
eventos, las últimas líneas de log y los NOMBRES de sus variables— y lo pasa
por reglas que reconocen las fallas conocidas. Cada hallazgo dice qué pasa,
muestra la evidencia (sin secretos) y propone una acción de una lista segura.

Las reglas no usan IA a propósito: responden al instante, no sacan datos del
clúster y se pueden probar. Lo que no reconocen queda como evidencia para una
persona, un agente conectado por MCP o, más adelante, un modelo.

`collect` lee el clúster; `analyze` es puro y es donde viven las reglas.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.services import db_env
from app.services.app_variables import looks_secret

LOG_TAIL = 120
EVIDENCE_LINES = 12
STALE_VOLUME_MINUTES = 10

ALTA, MEDIA, INFO = "alta", "media", "info"

# ── Enmascarado ──────────────────────────────────────────────────────────────
_MASKS = (
    (re.compile(r"(://[^:/@\s'\"]+):[^@\s'\"]+@"), r"\1:****@"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1****"),
    (re.compile(r"\bkbl_[0-9a-f]+_[A-Za-z0-9_-]+"), "kbl_****"),
    (re.compile(
        r"(?i)(?<![a-z])(password|passwd|pwd|secret|token|api[_-]?key|authorization)"
        r"(['\"]?\s*[=:]\s*['\"]?)(?!os\.environ|os\.getenv|process\.env|bearer\b)([^\s,'\"]{3,})"
    ), r"\1\2****"),
)


def mask(line: str) -> str:
    for pattern, replacement in _MASKS:
        line = pattern.sub(replacement, line)
    return line


# ── Recolección (Kubernetes) ─────────────────────────────────────────────────
def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


def _container(spec_containers: List[Any], app_name: str) -> Any:
    return next((c for c in spec_containers if c.name == app_name), spec_containers[0])


def _pod_ready(pod: Any) -> bool:
    statuses = pod.status.container_statuses or []
    return bool(statuses) and bool(statuses[0].ready)


def collect(app_name: str, namespace: str) -> Dict[str, Any]:
    """Todo lo que el diagnóstico necesita saber, leído del clúster. Nunca valores de secretos."""
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    core, apps_api = client.CoreV1Api(), client.AppsV1Api()
    bundle: Dict[str, Any] = {"app": app_name, "namespace": namespace, "workload": {"exists": False},
                              "revisions": [], "pods": [], "events": [], "logs": {"lines": []},
                              "env_names": [], "ports": [], "probes": [], "databases": []}

    workload = None
    for kind, reader in (("Deployment", apps_api.read_namespaced_deployment),
                         ("StatefulSet", apps_api.read_namespaced_stateful_set)):
        try:
            workload = reader(app_name, namespace)
            bundle["workload"] = {
                "exists": True, "kind": kind,
                "desired": workload.spec.replicas if workload.spec.replicas is not None else 1,
                "ready": workload.status.ready_replicas or 0,
                "updated": workload.status.updated_replicas or 0,
                "conditions": [
                    {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                    for c in (workload.status.conditions or [])
                ],
            }
            break
        except ApiException as exc:
            if exc.status != 404:
                raise
    if workload is None:
        return bundle

    selector = f"app={app_name}"
    if bundle["workload"]["kind"] == "Deployment":
        for rs in apps_api.list_namespaced_replica_set(namespace, label_selector=selector).items:
            owners = [o.name for o in (rs.metadata.owner_references or [])]
            if app_name not in owners:
                continue
            bundle["revisions"].append({
                "name": rs.metadata.name,
                "revision": int((rs.metadata.annotations or {}).get("deployment.kubernetes.io/revision", "0") or 0),
                "image": rs.spec.template.spec.containers[0].image,
                "desired": rs.spec.replicas or 0,
                "ready": rs.status.ready_replicas or 0,
                "created": _iso(rs.metadata.creation_timestamp),
            })
        bundle["revisions"].sort(key=lambda r: r["revision"])

    pods = core.list_namespaced_pod(namespace, label_selector=selector).items
    pods.sort(key=lambda p: p.metadata.creation_timestamp)
    for pod in pods:
        status = (pod.status.container_statuses or [None])[0]
        waiting = status.state.waiting if status and status.state else None
        terminated = status.last_state.terminated if status and status.last_state else None
        owners = pod.metadata.owner_references or []
        bundle["pods"].append({
            "name": pod.metadata.name,
            "owner": owners[0].name if owners else None,
            "created": _iso(pod.metadata.creation_timestamp),
            "phase": pod.status.phase,
            "ready": bool(status and status.ready),
            "restarts": status.restart_count if status else 0,
            "image": status.image if status else _container(pod.spec.containers, app_name).image,
            "waiting_reason": waiting.reason if waiting else None,
            "waiting_message": mask(waiting.message or "") if waiting else None,
            "last_reason": terminated.reason if terminated else None,
            "last_exit_code": terminated.exit_code if terminated else None,
        })

    # El pod que interesa es el que falla; si todos están bien, el más nuevo.
    target = next((p for p in reversed(pods) if not _pod_ready(p)), pods[-1] if pods else None)
    if target is not None:
        container = _container(target.spec.containers, app_name)
        bundle["ports"] = [p.container_port for p in (container.ports or [])]
        for probe_name in ("readiness_probe", "liveness_probe"):
            probe = getattr(container, probe_name)
            if probe and probe.http_get:
                headers = {h.name.lower(): h.value for h in (probe.http_get.http_headers or [])}
                bundle["probes"].append({"kind": probe_name.split("_")[0], "path": probe.http_get.path,
                                         "port": probe.http_get.port, "host_header": headers.get("host")})
        names = {e.name for e in (container.env or [])}
        for source in container.env_from or []:
            try:
                if source.secret_ref:
                    names.update((core.read_namespaced_secret(source.secret_ref.name, namespace).data or {}).keys())
                elif source.config_map_ref:
                    names.update((core.read_namespaced_config_map(source.config_map_ref.name, namespace).data or {}).keys())
            except ApiException:
                continue
        bundle["env_names"] = sorted(names)

        status = (target.status.container_statuses or [None])[0]
        lines: List[str] = []
        if status and status.restart_count:
            lines += _pod_log(core, target.metadata.name, namespace, container.name, previous=True)
        lines += _pod_log(core, target.metadata.name, namespace, container.name, previous=False)
        bundle["logs"] = {"pod": target.metadata.name, "lines": lines[-LOG_TAIL * 2:]}

    for event in core.list_namespaced_event(namespace).items:
        involved = event.involved_object.name or ""
        if involved != app_name and not involved.startswith(f"{app_name}-"):
            continue
        bundle["events"].append({
            "object": involved, "kind": event.involved_object.kind, "type": event.type,
            "reason": event.reason, "message": mask(event.message or ""), "count": event.count or 1,
            "last_seen": _iso(event.last_timestamp or event.event_time),
        })
    bundle["events"].sort(key=lambda e: e["last_seen"] or "")
    bundle["events"] = bundle["events"][-30:]

    bundle["databases"] = _databases(core, apps_api, namespace, bundle["env_names"], ApiException)
    return bundle


def _pod_log(core: Any, pod: str, namespace: str, container: str, *, previous: bool) -> List[str]:
    try:
        text = core.read_namespaced_pod_log(pod, namespace, container=container, tail_lines=LOG_TAIL, previous=previous)
    except Exception:
        return []
    return (text or "").splitlines()


def binding_prefixes(env_names: Iterable[str]) -> List[str]:
    """Prefijos de las bases vinculadas ('NORTH_STAR_BAY_BD_URI' → 'NORTH_STAR_BAY_BD')."""
    names = set(env_names)
    return sorted(
        name[: -len("_URI")] for name in names
        if name.endswith("_URI") and name not in db_env.CANONICAL_NAMES
        and f"{name[:-len('_URI')]}_PASSWORD" in names and f"{name[:-len('_URI')]}_HOST" in names
    )


def _databases(core: Any, apps_api: Any, namespace: str, env_names: List[str], api_exception: Any) -> List[Dict[str, Any]]:
    """Para cada base vinculada: cuándo se creó su volumen y cuándo sus credenciales actuales."""
    found = []
    pvcs = core.list_namespaced_persistent_volume_claim(namespace).items
    for prefix in binding_prefixes(env_names):
        name = prefix.lower().replace("_", "-")
        try:
            sts = apps_api.read_namespaced_stateful_set(name, namespace)
        except api_exception:
            continue
        secrets = set()
        for container in sts.spec.template.spec.containers:
            secrets.update(s.secret_ref.name for s in (container.env_from or []) if s.secret_ref)
            secrets.update(e.value_from.secret_key_ref.name for e in (container.env or [])
                           if e.value_from and e.value_from.secret_key_ref)
        created = []
        for secret in secrets:
            try:
                created.append(core.read_namespaced_secret(secret, namespace).metadata.creation_timestamp)
            except api_exception:
                continue
        volumes = [p.metadata.creation_timestamp for p in pvcs if p.metadata.name.endswith(f"-{name}-0")]
        found.append({
            "name": name,
            "volume_created": _iso(min(volumes)) if volumes else None,
            "credentials_created": _iso(max(created)) if created else None,
        })
    return found


# ── Reglas ───────────────────────────────────────────────────────────────────
_KEY_ERROR = re.compile(r"KeyError: ['\"]([A-Z][A-Z0-9_]{1,63})['\"]")
_ENV_LIKE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
_ENV_PHRASES = (
    re.compile(r"(?i:missing|required)\s+(?i:environment|env)(?:\s+(?i:variable))?s?\s*[:=]?\s*['\"]?([A-Z][A-Z0-9_]{2,63})\b"),
    re.compile(r"(?i:environment variable|env var(?:iable)?)\s+['\"]?([A-Z][A-Z0-9_]{2,63})['\"]?\s+(?i:is\s+)?(?i:not set|missing|required|undefined|not defined)"),
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]{2,63})\s+(?i:is\s+)?(?i:undefined|not defined|required|missing)"),
)
_PYDANTIC_FIELD = re.compile(r"^([a-z][a-z0-9_]{1,63})$")
_DB_AUTH = (
    re.compile(r"(?i)authentication failed|AuthenticationFailed"),
    re.compile(r'password authentication failed for user "?[\w.-]+'),
    re.compile(r"Access denied for user '[^']+'@"),
    re.compile(r"WRONGPASS|NOAUTH Authentication required"),
)
_DB_WORDS = re.compile(r"(?i)mongo|postgres|psycopg|mysql|mariadb|redis|database|sqlalchemy|prisma")
_MODULE = (
    re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]"),
    re.compile(r"Error: Cannot find module ['\"]([^'\"]+)['\"]"),
)
_LISTENING = (
    re.compile(r"(?i:uvicorn running on|listening on|server running on|started server on)\s+(?:https?://)?[\w.\[\]-]*:(\d{2,5})\b"),
    re.compile(r"(?i:listening on port|running on port|server started on port)\s+(\d{2,5})\b"),
)
_PROBE_STATUS = re.compile(r"(Readiness|Liveness|Startup) probe failed: HTTP probe failed with statuscode: (\d{3})")
_PROBE_REFUSED = re.compile(r"(Readiness|Liveness|Startup) probe failed: .*connection refused")
_EXCEPTION_LINE = re.compile(r"^\s*(?:[A-Za-z_][\w.]*(?:Error|Exception|Failure)|Error)\b.*")


def _finding(code, severity, title, detail, evidence=(), actions=(), **extra) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "title": title, "detail": detail,
            "evidence": [mask(line) for line in evidence][:EVIDENCE_LINES], "actions": list(actions), **extra}


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _missing_variables(lines: List[str], env_names: set) -> List[tuple]:
    found: Dict[str, str] = {}
    for index, line in enumerate(lines):
        match = _KEY_ERROR.search(line)
        if match:
            name = match.group(1)
            near_environ = any("environ" in previous for previous in lines[max(0, index - 6):index])
            if near_environ or _ENV_LIKE.match(name):
                found.setdefault(name, line)
            continue
        for pattern in _ENV_PHRASES:
            match = pattern.search(line)
            if match:
                found.setdefault(match.group(1), line)
        if "Field required" in line and index > 0:
            field = _PYDANTIC_FIELD.match(lines[index - 1].strip())
            if field:
                found.setdefault(field.group(1).upper(), f"{lines[index - 1].strip()}: {line.strip()}")
    return [(name, line) for name, line in found.items() if name not in env_names]


def _variable_action(name: str) -> Dict[str, Any]:
    if name in db_env.CANONICAL_NAMES:
        return {"id": "repair_db_bindings", "label": "Publicar los nombres estándar de la base"}
    generate = looks_secret(name)
    return {"id": "set_app_variable", "variable": name, "generate": generate,
            "label": f"Generar un valor seguro para {name}" if generate else f"Agregar {name}"}


def _crashing(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p for p in bundle.get("pods", []) if not p["ready"] and (
        p.get("waiting_reason") in ("CrashLoopBackOff", "Error") or p.get("last_reason") == "Error"
        or (p.get("restarts") or 0) > 0)]


def _healthy(bundle: Dict[str, Any]) -> bool:
    workload = bundle.get("workload") or {}
    revisions = bundle.get("revisions") or []
    newest_ok = not revisions or revisions[-1]["ready"] >= revisions[-1]["desired"]
    pods_ok = all(p.get("ready") for p in bundle.get("pods") or [])
    return bool(workload.get("exists") and workload.get("ready", 0) >= workload.get("desired", 1)
                and newest_ok and pods_ok)


def _stuck_rollout(bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    revisions = bundle.get("revisions") or []
    conditions = (bundle.get("workload") or {}).get("conditions") or []
    deadline = any(c.get("type") == "Progressing" and c.get("reason") == "ProgressDeadlineExceeded" for c in conditions)
    if len(revisions) < 2 and not deadline:
        return None
    newest = revisions[-1] if revisions else None
    serving = [r for r in revisions[:-1] if r["ready"] > 0]
    if newest and newest["desired"] > 0 and newest["ready"] < newest["desired"] and serving:
        old = serving[-1]
        restarts = sum(p.get("restarts") or 0 for p in bundle.get("pods", []) if p.get("owner") == newest["name"])
        return _finding(
            "stuck_rollout", ALTA,
            "La versión nueva no arranca; la anterior sigue atendiendo",
            f"La versión {newest['image']} (desde {newest['created'] or '—'}) no queda lista"
            + (f" tras {restarts} reinicios" if restarts else "")
            + f", así que sigue respondiendo {old['image']}. Los cambios que se desplegaron no se ven "
            "hasta que la versión nueva arranque. Los otros hallazgos dicen por qué no arranca.",
            new_image=newest["image"], serving_image=old["image"],
        )
    if deadline and not _healthy(bundle):
        return _finding("stuck_rollout", ALTA, "El despliegue lleva demasiado tiempo sin terminar",
                        "Kubernetes dio por vencido el despliegue: los pods nuevos no quedan listos.")
    return None


def _database_auth(lines: List[str], bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    databases = bundle.get("databases") or []
    hits = [line for line in lines if any(p.search(line) for p in _DB_AUTH) and (databases or _DB_WORDS.search(line))]
    if not hits:
        return None
    detail = ("La base de datos rechaza el usuario y la contraseña con que se conecta la app. "
              "La app no puede arrancar hasta que coincidan.")
    stale = []
    for database in databases:
        volume, credentials = _parse_time(database.get("volume_created")), _parse_time(database.get("credentials_created"))
        if volume and credentials and (credentials - volume).total_seconds() > STALE_VOLUME_MINUTES * 60:
            stale.append(database)
    if stale:
        db = stale[0]
        detail += (
            f" El disco de {db['name']} es de {db['volume_created'][:16].replace('T', ' ')} y sus credenciales "
            f"actuales de {db['credentials_created'][:16].replace('T', ' ')}: la base se volvió a crear con el "
            "mismo nombre y el disco conserva la contraseña anterior (Mongo y Postgres solo la aplican al "
            "iniciar un disco vacío). Si esa base no tiene datos que conservar, reinicializarla lo resuelve; "
            "si los tiene, hay que volver a la contraseña anterior. Pide ayuda a quien administra la plataforma."
        )
    return _finding("database_auth_failed", ALTA, "La base de datos rechaza las credenciales de la app",
                    detail, evidence=hits[-3:], database=stale[0]["name"] if stale else None)


def analyze(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Hallazgos en lenguaje simple, del más útil al menos, a partir de lo recolectado."""
    app, namespace = bundle.get("app"), bundle.get("namespace")
    workload = bundle.get("workload") or {}
    base = {"app": app, "env": namespace, "checked_at": datetime.now(timezone.utc).isoformat()}

    if not workload.get("exists"):
        finding = _finding("not_deployed", ALTA, "No hay nada desplegado en este ambiente",
                           f"No existe {app} en '{namespace}'. Si la app debería estar aquí, sincronízala con ArgoCD.",
                           actions=[{"id": "sync_app", "label": "Sincronizar con ArgoCD"}])
        return {**base, "status": "problem", "summary": finding["title"], "findings": [finding], "pods": []}

    pods = bundle.get("pods") or []
    pods_view = [{k: p.get(k) for k in ("name", "ready", "restarts", "image", "waiting_reason", "last_reason")} for p in pods]
    if workload.get("desired") == 0:
        return {**base, "status": "ok", "summary": "La app está apagada en este ambiente (0 réplicas).",
                "findings": [], "pods": pods_view}
    if _healthy(bundle):
        image = (bundle.get("revisions") or [{}])[-1].get("image") or (pods[-1]["image"] if pods else "")
        summary = f"Todo en orden: {workload.get('ready')}/{workload.get('desired')} réplicas listas" + (f" ({image})." if image else ".")
        return {**base, "status": "ok", "summary": summary, "findings": [], "pods": pods_view}

    lines = (bundle.get("logs") or {}).get("lines") or []
    env_names = set(bundle.get("env_names") or [])
    findings: List[Dict[str, Any]] = []

    for pod in pods:
        reason = pod.get("waiting_reason")
        if reason in ("ErrImagePull", "ImagePullBackOff", "InvalidImageName"):
            findings.append(_finding(
                "image_pull", ALTA, "No se puede descargar la imagen de la app",
                f"Kubernetes no consigue bajar {pod['image']}: la etiqueta no existe, el registro pide "
                "credenciales o el pipeline no terminó de publicarla. Revisa el último pipeline de la app.",
                evidence=[pod.get("waiting_message") or reason]))
            break
    for pod in pods:
        if pod.get("waiting_reason") == "CreateContainerConfigError":
            findings.append(_finding(
                "config_error", ALTA, "Falta un secreto o una configuración que la app necesita",
                "Kubernetes no puede armar el contenedor porque falta algo que el despliegue referencia "
                "(normalmente un secreto). Sincronizar con ArgoCD lo vuelve a generar.",
                evidence=[pod.get("waiting_message") or ""],
                actions=[{"id": "sync_app", "label": "Sincronizar con ArgoCD"}]))
            break
    if any(p.get("last_reason") == "OOMKilled" for p in pods):
        findings.append(_finding(
            "out_of_memory", ALTA, "La app se queda sin memoria",
            "Kubernetes la detiene porque supera el límite de memoria asignado. Hay que subir el límite "
            "o bajar el consumo (cargar menos datos a la vez, cachés más chicos)."))

    for name, line in _missing_variables(lines, env_names):
        findings.append(_finding(
            "missing_env_var", ALTA, f"Tu código pide la variable {name} y la app no la recibe",
            f"La app se detiene al arrancar porque lee {name} y nadie se la entrega. "
            + ("Es un nombre estándar de conexión a la base: la plataforma puede publicarlo."
               if name in db_env.CANONICAL_NAMES else
               "Agrégala a la app; si es una contraseña o clave, la plataforma puede generarla."),
            evidence=[line], actions=[_variable_action(name)], variable=name))

    auth = _database_auth(lines, bundle)
    if auth:
        findings.append(auth)

    for pattern in _MODULE:
        match = next((m for m in (pattern.search(line) for line in lines) if m), None)
        if match:
            findings.append(_finding(
                "missing_dependency", ALTA, f"Falta la dependencia '{match.group(1)}' en la imagen",
                "El código importa un paquete que no está instalado. Agrégalo a requirements.txt o "
                "package.json y vuelve a publicar la app.", evidence=[match.group(0)]))
            break

    listening = next((int(m.group(1)) for m in (p.search(line) for line in lines for p in _LISTENING) if m), None)
    expected = sorted({p["port"] for p in bundle.get("probes") or [] if isinstance(p.get("port"), int)} | set(bundle.get("ports") or []))
    if listening and expected and listening not in expected:
        findings.append(_finding(
            "port_mismatch", ALTA, f"La app escucha en el puerto {listening}, pero la plataforma la busca en {expected[0]}",
            f"El contenedor arranca, pero nadie puede hablarle: escucha en {listening} y el servicio y las "
            f"comprobaciones de salud apuntan a {', '.join(map(str, expected))}. Hay que alinear el puerto."))

    probe_events = [e for e in bundle.get("events") or [] if e.get("reason") == "Unhealthy"]
    rejected = next((m for m in (_PROBE_STATUS.search(e["message"]) for e in reversed(probe_events)) if m), None)
    if rejected:
        code = int(rejected.group(2))
        probe = next((p for p in bundle.get("probes") or [] if p["kind"] == rejected.group(1).lower()), {})
        if code in (400, 403, 421) and not probe.get("host_header"):
            detail = (f"La app responde {code} a la comprobación de salud de Kubernetes. Suele pasar cuando la app "
                      "valida el encabezado Host (orígenes permitidos, ALLOWED_HOSTS): Kubernetes llama con la IP "
                      "del pod. Hay que permitir 'localhost' en la app o configurar la sonda con Host: localhost.")
        elif code == 404:
            detail = f"La comprobación de salud llama a {probe.get('path') or 'una ruta'} y la app responde 404: esa ruta no existe."
        else:
            detail = f"La comprobación de salud recibe {code} de la app, así que Kubernetes no la da por lista."
        findings.append(_finding("probe_rejected", ALTA, "La app rechaza la comprobación de salud", detail,
                                 evidence=[rejected.group(0)]))
    elif not listening and any(_PROBE_REFUSED.search(e["message"]) for e in probe_events):
        findings.append(_finding(
            "probe_refused", MEDIA, "Nadie contesta en el puerto que revisa la plataforma",
            "La comprobación de salud no logra conectarse: la app todavía no arrancó, se cae antes, o escucha "
            "en otro puerto o solo en 127.0.0.1 (debe escuchar en 0.0.0.0)."))

    specific = {f["code"] for f in findings}
    stuck = _stuck_rollout(bundle)
    if stuck:
        findings.append(stuck)
    if _crashing(bundle) and not specific:
        exception = next((line for line in reversed(lines) if _EXCEPTION_LINE.match(line)), None)
        findings.append(_finding(
            "crash", ALTA, "La app se detiene al arrancar",
            "No reconozco este error todavía. Estas son las últimas líneas del log: quien mantiene el código "
            "(o un agente conectado por MCP) puede leerlas para encontrar la causa."
            + (f" El error final es: {mask(exception.strip())}" if exception else ""),
            evidence=[line for line in lines if line.strip()][-EVIDENCE_LINES:]))

    if not findings:
        findings.append(_finding(
            "starting", INFO, "La app todavía se está desplegando",
            "Hay pods que aún no están listos pero no muestran errores. Si sigue así varios minutos, vuelve a diagnosticar."))

    return {**base, "status": "problem", "summary": findings[0]["title"], "findings": findings, "pods": pods_view}


async def diagnose(app_name: str, namespace: str) -> Dict[str, Any]:
    import asyncio

    bundle = await asyncio.to_thread(collect, app_name, namespace)
    return analyze(bundle)
