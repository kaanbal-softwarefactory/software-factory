"""
Qué cambia, antes de cambiarlo
==============================

Los planes de lo que crea apps o mueve lo que se ve en internet: alta de una app,
lanzamiento de un stack, exposición, mudanza de dominio y homepage. Cada función
recibe lo ya leído de la base y devuelve el plan, o ChangeError con el motivo y
el código HTTP que corresponde.

Las mismas funciones validan el dry_run y la ejecución real: el plan que ve la
persona y lo que después se aplica no pueden discrepar en las reglas, solo en el
estado (y para eso está el plan_id, ver plans.py).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.services import domain_service

EXPOSURE_MODES = ("public", "tailscale", "lan", "internal", "off", "both")
PUBLIC_MODES = domain_service.PUBLIC_MODES


class ChangeError(ValueError):
    """El cambio no se puede hacer así. `status` es el código HTTP que lo explica."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _url(app_name: str, env: str, fqdn: str, mode: Optional[str], *, is_root: bool) -> Optional[str]:
    if not fqdn or mode not in PUBLIC_MODES:
        return None
    return f"https://{domain_service.public_host(app_name, env, fqdn, is_root_domain=is_root)}"


def busy_reason(tasks: Mapping[str, Optional[Mapping[str, Any]]]) -> Optional[str]:
    """Una app cambia de a una cosa: dos coreografías de exposición a la vez se pisan en infra-gitops."""
    labels = {
        "domain_move": "una mudanza de dominio",
        "root_promotion": "una conversión en homepage",
        "exposure_change": "un cambio de exposición",
    }
    for key, label in labels.items():
        task = tasks.get(key)
        if task and task.get("state") == "running":
            return f"Ya hay {label} en curso para esta app. Espera a que termine (deploy_status la muestra)."
    return None


# ── Alta de una app y stacks ─────────────────────────────────────────────
def _plain(value: Any) -> Any:
    """ExposureType.PUBLIC → 'public'. Un documento recién armado trae los enums del modelo;
    str() de un enum (str, Enum) da 'ExposureType.PUBLIC', no 'public'. En Mongo llegan como texto."""
    return getattr(value, "value", value)


def _plain_exposure(doc: Mapping[str, Any]) -> Dict[str, Any]:
    exposure = dict(doc.get("exposure") or {})
    exposure["type"] = _plain(exposure.get("type"))
    exposure["per_env"] = {env: _plain(mode) for env, mode in (exposure.get("per_env") or {}).items()}
    return {**doc, "exposure": exposure}


def app_plan(doc: Mapping[str, Any], fqdn: str, *, creation_mode: str,
             database_bindings: Optional[Mapping[str, List[Mapping[str, Any]]]] = None) -> Dict[str, Any]:
    """Plan de POST /apps a partir del documento ya validado (create_app_record sin insertar)."""
    doc = _plain_exposure(doc)
    name = doc["name"]
    is_root = bool(doc.get("is_root_domain"))
    modes = domain_service.env_modes(doc)
    urls = {env: _url(name, env, fqdn, mode, is_root=is_root) for env, mode in modes.items()}
    urls = {env: url for env, url in urls.items() if url}
    databases = {
        env: sorted({str(b.get("app_name")) for b in (items or []) if b.get("app_name")})
        for env, items in (database_bindings or {}).items()
    }
    databases = {env: names for env, names in databases.items() if names}

    steps = []
    if creation_mode == "config-only":
        steps.append("Desplegar la imagen oficial de la plantilla (sin repositorio de código).")
    else:
        steps.append(f"Crear el repositorio '{name}' con el código de la plantilla, su Dockerfile y su pipeline.")
    steps.append("Generar sus secretos (en Vault) y sus manifiestos en infra-gitops.")
    for env, names in databases.items():
        steps.append(f"Conectar {env} a {', '.join(names)}: credenciales y nombres estándar (MONGO_URI, DATABASE_URL…).")
    for env, url in urls.items():
        steps.append(f"Publicar {url} (DNS en Cloudflare) y probar que responda.")
    steps.append("Desplegar con ArgoCD. Tarda unos minutos: el avance se ve con deploy_status.")

    return {
        "action": "create_app",
        "name": name,
        "template": doc.get("template"),
        "category": doc.get("category"),
        "group": doc.get("app_group"),
        "domain": fqdn,
        "environments": list(doc.get("environments") or []),
        "exposure": modes,
        "urls": urls,
        "is_homepage": is_root,
        "creation_mode": creation_mode,
        "databases": databases,
        "steps": steps,
    }


def stack_plan_view(plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Lo que la persona necesita ver de un plan de stack (stack_launcher.build_plan)."""
    by_role = {component["role"]: component for component in plan["components"]}
    components = []
    for component in plan["components"]:
        mode = (component.get("exposure") or {}).get("type")
        connects_to = None
        if component.get("database_bindings"):
            connects_to = (by_role.get("database") or {}).get("name")
        elif (component.get("template_config") or {}).get("API_APP"):
            connects_to = component["template_config"]["API_APP"]
        components.append({
            "role": component["role"],
            "name": component["name"],
            "template": component["template"],
            "exposure": mode,
            "url": f"https://{component['public_host']}" if component.get("public_host") else None,
            "is_homepage": bool(component.get("is_root_domain")),
            "connects_to": connects_to,
        })
    steps = [
        f"Crear {len(components)} apps en orden ({' → '.join(c['name'] for c in components)}): cada una espera "
        "a que la anterior esté lista, porque la API necesita las credenciales de la base y el frontend la URL de la API.",
        "Si una pieza falla, el stack se detiene ahí y lo creado queda en pie (se reintenta o se borra desde la consola).",
        "Tarda varios minutos: el avance se ve con deploy_status(run_id=...).",
    ]
    return {
        "action": "launch_stack",
        "stack": plan["stack_id"],
        "stack_name": plan.get("stack_name"),
        "base": plan["base"],
        "group": plan["group"],
        "domain": plan["domain"],
        "environments": list(plan["environments"]),
        "homepage": bool(plan["homepage"]),
        "components": components,
        "steps": steps,
    }


# ── Exposición ───────────────────────────────────────────────────────────
def exposure_plan(app: Mapping[str, Any], fqdn: str, per_env: Mapping[str, Any]) -> Dict[str, Any]:
    """Qué pasa con cada ambiente al cambiar su exposición."""
    name = app["name"]
    if not isinstance(per_env, Mapping) or not per_env:
        raise ChangeError("Indica el modo de al menos un ambiente, por ejemplo {\"prod\": \"public\"}.", 400)
    if (app.get("exposure") or {}).get("port_exposure"):
        raise ChangeError(
            f"'{name}' expone varios puertos con modos distintos: cambia su exposición desde la consola "
            "(Manage exposure), donde se ve cada puerto.", 422,
        )

    environments = list(app.get("environments") or ["prod"])
    current = domain_service.env_modes(app)
    is_root = bool(app.get("is_root_domain"))
    changes: Dict[str, Dict[str, Any]] = {}
    for env, raw_mode in per_env.items():
        mode = str(raw_mode or "").strip().lower()
        if env not in environments:
            raise ChangeError(f"'{name}' no tiene el ambiente '{env}' (tiene {', '.join(environments)}).", 400)
        if mode not in EXPOSURE_MODES:
            raise ChangeError(f"Modo '{raw_mode}' desconocido. Usa uno de: {', '.join(EXPOSURE_MODES)}.", 400)
        before = current.get(env)
        if mode == before:
            continue
        changes[env] = {
            "from": before,
            "to": mode,
            "url_before": _url(name, env, fqdn, before, is_root=is_root),
            "url_after": _url(name, env, fqdn, mode, is_root=is_root),
        }

    if not changes:
        raise ChangeError(f"'{name}' ya tiene esa exposición: no hay nada que cambiar.", 409)
    if is_root and "prod" in changes and changes["prod"]["to"] not in PUBLIC_MODES:
        raise ChangeError(
            f"'{name}' es el homepage de {fqdn}: su prod tiene que ser pública (el dominio desnudo apunta a ella).",
            422,
        )

    warnings = []
    for env, change in changes.items():
        if change["to"] == "off":
            warnings.append(f"{env} se apaga (0 réplicas) y deja de responder hasta que lo vuelvas a exponer.")
        elif change["url_before"] and not change["url_after"]:
            warnings.append(f"{change['url_before']} deja de responder desde internet.")
        elif change["url_after"] and not change["url_before"]:
            warnings.append(f"{change['url_after']} queda abierta en internet: cualquiera puede entrar.")
    return {
        "action": "set_exposure",
        "app": name,
        "domain": fqdn or None,
        "changes": changes,
        "warnings": warnings,
        "steps": [
            "Reescribir los overlays en infra-gitops y esperar a que ArgoCD los aplique.",
            "Publicar o retirar DNS y Tailscale, y probar las URLs nuevas.",
            "Corre en segundo plano (puede tardar unos minutos): el resultado se ve con deploy_status.",
        ],
    }


# ── Dominio ──────────────────────────────────────────────────────────────
def domain_move_plan(app: Mapping[str, Any], current: Mapping[str, Any], target_fqdn: str, *,
                     target_id: str, collisions: List[Mapping[str, Any]], busy: Optional[str] = None) -> Dict[str, Any]:
    """Mudar una app pública a otro dominio (mismas reglas que POST /apps/{app}/domain)."""
    name = app["name"]
    if not current.get("public"):
        raise ChangeError(
            "La app no tiene ambientes públicos: el dominio no aplica. Hazla pública desde su exposición primero.",
            400,
        )
    if current.get("id") == target_id:
        raise ChangeError(f"{name} ya vive en {target_fqdn}.", 409)
    if collisions:
        first = collisions[0]
        raise ChangeError(f"{', '.join(first['hosts'])} ya lo usa la app '{first['app']}' en {target_fqdn}.", 409)
    if busy:
        raise ChangeError(busy, 409)

    is_root = bool(app.get("is_root_domain"))
    urls_after = {
        env: _url(name, env, target_fqdn, mode, is_root=is_root)
        for env, mode in (current.get("modes") or {}).items() if mode in PUBLIC_MODES
    }
    warnings = [f"Las URLs de {current.get('fqdn')} dejan de responder cuando las de {target_fqdn} ya respondan."]
    if is_root:
        warnings.append(f"Es un homepage: pasa a ocupar la raíz de {target_fqdn}.")
    return {
        "action": "attach_domain",
        "app": name,
        "from": current.get("fqdn"),
        "to": target_fqdn,
        "urls_before": dict(current.get("urls") or {}),
        "urls_after": urls_after,
        "warnings": warnings,
        "steps": [
            "Publicar el DNS nuevo y reescribir el Ingress.",
            "Probar las URLs nuevas y, solo cuando respondan, retirar las anteriores.",
            "Corre en segundo plano: el resultado se ve con deploy_status.",
        ],
    }


# ── Homepage ─────────────────────────────────────────────────────────────
def homepage_plan(app: Mapping[str, Any], current: Mapping[str, Any], *, root_owner: Optional[str],
                  collisions: List[Mapping[str, Any]], busy: Optional[str] = None) -> Dict[str, Any]:
    """Dar a una app la raíz de su dominio (mismas reglas que POST /apps/{app}/homepage)."""
    name = app["name"]
    if app.get("is_root_domain"):
        raise ChangeError(f"{name} ya es el homepage de su dominio.", 409)
    if busy:
        raise ChangeError(busy, 409)
    fqdn = current.get("fqdn") or ""
    if not fqdn:
        raise ChangeError("La app no tiene dominio: regístralo antes de darle la raíz.", 400)
    if (current.get("modes") or {}).get("prod") not in PUBLIC_MODES:
        raise ChangeError(
            f"El homepage ocupa {fqdn}, así que su prod tiene que ser pública. "
            "Cámbiala en 'Manage exposure' (o con set_exposure) y vuelve a intentarlo.",
            422,
        )
    if root_owner:
        raise ChangeError(
            f"La raíz de {fqdn} ya la ocupa '{root_owner}'. Solo puede haber un homepage por dominio.", 409,
        )
    if collisions:
        first = collisions[0]
        raise ChangeError(f"{', '.join(first['hosts'])} ya lo usa la app '{first['app']}' en {fqdn}.", 409)

    return {
        "action": "set_homepage",
        "app": name,
        "domain": fqdn,
        "url_before": f"https://{domain_service.public_host(name, 'prod', fqdn)}",
        "url_after": f"https://{fqdn}",
        "warnings": [f"prod deja https://{domain_service.public_host(name, 'prod', fqdn)} y pasa a https://{fqdn}."],
        "steps": [
            "Reescribir el Ingress de prod con el dominio desnudo y enrutar la raíz en el túnel.",
            "Probar la URL; la app queda marcada como homepage solo si respondió.",
            "Corre en segundo plano: el resultado se ve con deploy_status.",
        ],
    }


# ── Vínculos ─────────────────────────────────────────────────────────────
def link_plan(app_name: str, provider_name: str, *, kind: str, alias: str,
              report: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Qué variables recibe cada ambiente al vincular (solo nombres: los valores no salen nunca)."""
    environments = {
        env: {"status": item.get("status"), "add": list(item.get("add") or []), "keep": list(item.get("keep") or [])}
        for env, item in report.items()
    }
    if not any(item["add"] for item in environments.values()):
        raise ChangeError(f"'{app_name}' ya tiene todo lo que da el vínculo con '{provider_name}': no hay nada que agregar.", 409)

    what = (
        "las credenciales de la base y los nombres estándar del motor (MONGO_URI, DATABASE_URL…)"
        if kind == "database" else f"dónde encontrar a '{provider_name}' dentro del clúster ({alias}_URL)"
    )
    warnings = []
    kept_standard = sorted({name for item in environments.values() for name in item["keep"] if not name.startswith(f"{alias}_")})
    if kept_standard:
        warnings.append(
            f"{', '.join(kept_standard)} ya existían y siguen como estaban: si apuntan a otra base, "
            f"usa las variables {alias}_* para llegar a '{provider_name}'."
        )
    return {
        "action": "link_apps",
        "app": app_name,
        "to": provider_name,
        "kind": kind,
        "alias": alias,
        "environments": environments,
        "warnings": warnings,
        "steps": [
            f"Agregar a '{app_name}' {what}, en su overlay de infra-gitops (los valores nunca salen de ahí).",
            "ArgoCD reinicia la app con las variables nuevas.",
        ],
    }


def unlink_plan(app_name: str, provider_name: str, names_by_env: Mapping[str, List[str]]) -> Dict[str, Any]:
    """Qué variables se quitan al deshacer un vínculo."""
    environments = {env: sorted(set(names or [])) for env, names in names_by_env.items()}
    return {
        "action": "unlink_apps",
        "app": app_name,
        "to": provider_name,
        "remove": environments,
        "warnings": [
            f"Si el código de '{app_name}' todavía usa estas variables, dejará de arrancar: revisa antes de quitarlo.",
        ],
        "steps": [
            "Quitar esas variables del overlay en infra-gitops (solo las que puso el vínculo).",
            "ArgoCD reinicia la app sin ellas.",
        ],
    }
