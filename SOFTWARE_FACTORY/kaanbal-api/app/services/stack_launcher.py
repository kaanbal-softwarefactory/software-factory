"""
Stacks — lanzar un sistema completo en una sola operación
=========================================================

Lo que todos armamos a mano —una base, una API vinculada a esa base y un
frontend que le pega— se lanza de una vez, en orden y ya cableado:

    base de datos  →  API (vinculada a la base)  →  frontend (apunta a la API)

El orden no es estético: la API necesita las credenciales de la base para
vincularse, y el frontend se construye con la URL real de su API dentro de la
imagen (Vite resuelve las variables en tiempo de build).

El plan se calcula **entero antes de crear nada**: nombres, dominio, grupo,
hosts públicos y vínculos. Así un choque de nombres o de hosts se ve antes de
que exista el primer repositorio, en vez de a mitad del stack.

Este módulo no toca la base de datos ni despliega: arma el plan. Quien lo
ejecuta es el router de stacks, que crea cada app por el mismo camino que el
Wizard (mismas validaciones, mismo deployer).
"""

from typing import Any, Dict, List, Optional

from app.services import db_env, domain_service

# Orden de despliegue. Lo que consume va después de lo que provee.
ROLE_ORDER = ("database", "backend", "frontend")

# Exposición por defecto de cada papel si el catálogo no dice otra cosa.
DEFAULT_EXPOSURE = {"database": "internal", "backend": "public", "frontend": "public"}

ROLE_CATEGORY = {"database": "database", "backend": "backend", "frontend": "frontend"}

# Modo de creación: las bases son imágenes oficiales, el resto se genera del template.
ROLE_CREATION_MODE = {"database": "config-only", "backend": "scaffold", "frontend": "scaffold"}


class StackPlanError(ValueError):
    """El stack no se puede lanzar tal como está pedido (el mensaje lo explica)."""


def normalize_base_name(raw: str, fqdn: str) -> str:
    """Nombre base del stack: lo que escribió el usuario, o el del dominio."""
    import re

    base = re.sub(r"[^a-z0-9-]", "", str(raw or "").strip().lower().replace("_", "-"))
    base = re.sub(r"-+", "-", base).strip("-")
    return base or domain_service.site_slug(fqdn)


def component_name(base: str, suffix: str) -> str:
    """'orbit' + '-api' → 'orbit-api'. El sufijo vacío deja el nombre base."""
    return f"{base}{suffix}" if suffix else base


def sort_components(components: List[dict]) -> List[dict]:
    """Base primero, luego API, al final frontend (ver el orden de arriba)."""
    return sorted(
        components,
        key=lambda c: ROLE_ORDER.index(c["role"]) if c.get("role") in ROLE_ORDER else len(ROLE_ORDER),
    )


def _binding_alias(db_app_name: str) -> str:
    """Mismo alias que usa el Wizard: el nombre de la base en mayúsculas."""
    return db_app_name.upper().replace("-", "_").replace(".", "_")


def build_plan(
    *,
    stack: dict,
    base_name: str,
    domain_fqdn: str,
    domain_id: Optional[str],
    environments: List[str],
    homepage: bool = False,
    group: Optional[str] = None,
    taken_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Plan completo del stack: qué apps se crean, con qué nombre y cómo se conectan.

    `homepage` da la raíz del dominio al frontend del stack: el sitio queda
    servido en el dominio desnudo y su API y su base cuelgan del mismo grupo.
    """
    components = sort_components(list(stack.get("components") or []))
    if not components:
        raise StackPlanError(f"El stack '{stack.get('id')}' no define componentes.")

    envs = [e for e in (environments or []) if e] or ["prod"]
    if "prod" not in envs:
        envs = [*envs, "prod"]

    base = normalize_base_name(base_name, domain_fqdn)
    stack_group = (group or base).strip().lower() or base
    taken = {str(n).lower() for n in (taken_names or [])}

    by_role: Dict[str, dict] = {}
    planned: List[dict] = []

    for component in components:
        role = component.get("role") or "backend"
        name = component_name(base, component.get("suffix") or "")
        if name.lower() in taken:
            raise StackPlanError(
                f"Ya existe una app llamada '{name}'. Elige otro nombre base para el stack "
                f"(cada pieza se nombra a partir de él)."
            )
        if any(p["name"].lower() == name.lower() for p in planned):
            raise StackPlanError(f"Dos componentes del stack se llamarían '{name}'.")

        is_root = bool(homepage and role == "frontend" and component.get("can_be_homepage"))
        mode = str(component.get("exposure") or DEFAULT_EXPOSURE.get(role, "internal"))
        if is_root:
            mode = "public"  # el homepage ES la URL pública del dominio

        entry = {
            "role": role,
            "name": name,
            "template": component["template"],
            "category": ROLE_CATEGORY.get(role, role),
            "creation_mode": component.get("creation_mode") or ROLE_CREATION_MODE.get(role, "scaffold"),
            "environments": list(envs),
            "exposure": {"type": mode, "per_env": {env: mode for env in envs}},
            "is_root_domain": is_root,
            "app_group": stack_group,
            "domain_id": domain_id,
            "public_host": (
                domain_service.public_host(name, "prod", domain_fqdn, is_root_domain=is_root)
                if mode in domain_service.PUBLIC_MODES else None
            ),
            "database_bindings": None,
            "template_config": {},
        }

        # Cableado: la API se vincula a la base; el frontend recibe la URL de la API.
        provider_role = component.get("binds") or component.get("consumes")
        provider = by_role.get(provider_role) if provider_role else None
        if provider_role and provider is None:
            raise StackPlanError(
                f"El componente '{role}' del stack espera un '{provider_role}' que el stack no define."
            )

        if component.get("binds") and provider:
            entry["database_bindings"] = {
                env: [{
                    "app_name": provider["name"],
                    "env": env,
                    "template": provider["template"],
                    "alias": _binding_alias(provider["name"]),
                }]
                for env in envs
            }
            engine = db_env.engine_from_template(provider["template"]) or provider["template"]
            entry["template_config"] = {
                "DB_ENGINE": engine,
                "DB_APP": provider["name"],
                "DB_ALIAS": _binding_alias(provider["name"]),
            }

        if component.get("consumes") and provider:
            api_url = f"https://{provider['public_host']}" if provider.get("public_host") else (
                f"http://{provider['name']}.prod.svc.cluster.local"
            )
            entry["template_config"] = {
                **entry["template_config"],
                "API_URL": api_url,
                "API_APP": provider["name"],
            }

        if is_root:
            # Igual que el Wizard: así el deployer sabe que va en la raíz.
            entry["template_config"] = {**entry["template_config"], "use_root_domain": True}

        planned.append(entry)
        by_role[role] = entry

    return {
        "stack_id": stack.get("id"),
        "stack_name": stack.get("name") or stack.get("id"),
        "base": base,
        "group": stack_group,
        "domain": domain_fqdn,
        "domain_id": domain_id,
        "environments": envs,
        "homepage": bool(homepage and any(c["is_root_domain"] for c in planned)),
        "components": planned,
    }


def app_create_payload(component: dict, *, description: str = "") -> Dict[str, Any]:
    """Componente del plan → cuerpo de POST /apps (el mismo que manda el Wizard)."""
    payload = {
        "name": component["name"],
        "template": component["template"],
        "category": component["category"],
        "app_group": component["app_group"],
        "description": description,
        "domain_id": component["domain_id"],
        "environments": component["environments"],
        "creation_mode": component["creation_mode"],
        "exposure": component["exposure"],
        "template_config": component["template_config"] or {},
    }
    if component.get("database_bindings"):
        payload["database_bindings"] = component["database_bindings"]
    return payload


def public_urls(plan: dict) -> Dict[str, str]:
    """URLs que quedarán publicadas, por papel. Para contarlo al terminar."""
    return {
        component["role"]: f"https://{component['public_host']}"
        for component in plan["components"] if component.get("public_host")
    }
