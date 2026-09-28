"""
El alta de una app a partir de lo poco que se dice
==================================================

El Wizard pregunta muchas cosas, y casi todas tienen una respuesta obvia según
la plantilla: el puerto, si se genera código o se usa una imagen oficial, qué se
publica en internet y qué queda en la VPN. Aquí se arma el mismo cuerpo de
POST /apps que manda el Wizard, con esas mismas respuestas por defecto, a partir
de una frase: "una API FastAPI llamada tienda-api, conectada a tienda-db".

Es puro a propósito: recibe la plantilla y las apps involucradas ya leídas, y
no toca la base ni el clúster. Quien lo usa (el MCP) valida el resultado contra
la API con un dry_run antes de crear nada.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.services import db_env

ENVIRONMENTS = ("dev", "staging", "prod")

# Los mismos valores por defecto que el Wizard (Wizard.vue, al elegir plantilla).
CATEGORY_EXPOSURE = {
    "database": "internal",
    "monitoring": "tailscale",
    "devtools": "tailscale",
    "workflow": "public",
    "frontend": "public",
    "backend": "public",
    "iot": "tailscale",
    "messaging": "tailscale",
}
# Dev y staging de lo que se ve en un navegador quedan en la VPN: "uno en internet,
# otro para probar" sin configurar nada.
NON_PROD_ON_VPN = frozenset({"frontend", "backend", "workflow"})

# Lo que se puede pedir al crear. "both" (rutas públicas y el resto por VPN) y los
# puertos múltiples se configuran en el Wizard, donde se ve cada superficie.
CREATE_EXPOSURES = ("public", "tailscale", "internal", "lan")

READY_STATUSES = ("ready", "beta")


class BlueprintError(ValueError):
    """La app no se puede armar así; el mensaje le dice a la persona qué cambiar."""


def environments_for(requested: Optional[List[str]]) -> List[str]:
    """Ambientes pedidos, sin repetir y en orden. Prod siempre está, como en el Wizard."""
    wanted = [str(env).strip().lower() for env in (requested or []) if str(env).strip()]
    unknown = sorted({env for env in wanted if env not in ENVIRONMENTS})
    if unknown:
        raise BlueprintError(f"Ambiente(s) desconocido(s): {', '.join(unknown)}. Usa dev, staging o prod.")
    chosen = set(wanted) | {"prod"}
    return [env for env in ENVIRONMENTS if env in chosen]


def binding_alias(app_name: str) -> str:
    """Prefijo de las variables de una base: el nombre de la base en mayúsculas (igual que el Wizard)."""
    return app_name.upper().replace("-", "_").replace(".", "_")


def _exposure(template: Mapping[str, Any], category: str, environments: List[str], explicit: Optional[str]) -> Dict[str, Any]:
    if explicit:
        mode = str(explicit).strip().lower()
        if mode not in CREATE_EXPOSURES:
            raise BlueprintError(
                f"Exposición '{explicit}' no disponible al crear: usa {', '.join(CREATE_EXPOSURES)}."
            )
        return {"type": mode, "per_env": {env: mode for env in environments}}

    catalog_mode = str(((template.get("exposure") or {}).get("mode")) or "")
    mode = catalog_mode if catalog_mode and catalog_mode != "both" else CATEGORY_EXPOSURE.get(category, "public")
    non_prod = "tailscale" if category in NON_PROD_ON_VPN else mode
    return {"type": mode, "per_env": {env: (mode if env == "prod" else non_prod) for env in environments}}


def build(
    template: Mapping[str, Any],
    *,
    name: str,
    environments: Optional[List[str]] = None,
    exposure: Optional[str] = None,
    domain_id: Optional[str] = None,
    homepage: bool = False,
    group: Optional[str] = None,
    description: str = "",
    database: Optional[Mapping[str, Any]] = None,
    api: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Cuerpo de POST /apps.

    `database` y `api` son las apps (como las devuelve GET /apps/{name}) a las que
    se conecta la nueva: la base se vincula con sus credenciales, igual que en el
    Wizard; la URL de la API queda en el build del frontend (VITE_API_URL).
    """
    template_id = str(template.get("id") or "")
    if not template_id:
        raise BlueprintError("Falta la plantilla.")
    status = str(template.get("status") or "ready")
    if status not in READY_STATUSES:
        raise BlueprintError(f"La plantilla '{template_id}' todavía no está disponible ({status}).")
    if len(template.get("ports") or []) > 1:
        raise BlueprintError(
            f"'{template_id}' expone varios puertos (cada uno con su exposición): créala desde el Wizard "
            "de la consola, donde se ve cada superficie."
        )

    category = str(template.get("category") or "")
    envs = environments_for(environments)
    modes = list(template.get("creation_modes") or ["scaffold"])
    creation_mode = "scaffold" if "scaffold" in modes else modes[0]

    exposure_config = _exposure(template, category, envs, exposure)
    if homepage:
        # El homepage ES la URL pública del dominio: su prod no puede ser otra cosa.
        exposure_config["per_env"]["prod"] = "public"

    template_config: Dict[str, Any] = {}
    if homepage:
        template_config["use_root_domain"] = True

    payload: Dict[str, Any] = {
        "name": name,
        "template": template_id,
        "category": category or None,
        "app_group": group or None,
        "description": description or "",
        "domain_id": domain_id,
        "environments": envs,
        "creation_mode": creation_mode,
        "exposure": exposure_config,
        "specs": {"replicas": 1, "port": int(template.get("port") or 80)},
    }

    if database is not None:
        if category == "frontend":
            raise BlueprintError(
                "Un frontend no se conecta a la base: todo lo que va en su build lo ve quien abre la página. "
                "Conéctalo a la API con api=<nombre de la API>."
            )
        db_name = str(database.get("name") or "")
        engine = db_env.engine_from_template(database.get("template"))
        if not engine:
            raise BlueprintError(f"'{db_name}' no es una base de datos (plantilla {database.get('template')}).")
        missing = [env for env in envs if env not in (database.get("environments") or ["prod"])]
        if missing:
            raise BlueprintError(
                f"La base '{db_name}' no tiene el ambiente {', '.join(missing)}: cada ambiente de la app se "
                "conecta a la base de su mismo ambiente."
            )
        alias = binding_alias(db_name)
        payload["database_bindings"] = {
            env: [{"app_name": db_name, "env": env, "template": database.get("template"), "alias": alias}]
            for env in envs
        }
        template_config.update({"DB_ENGINE": engine, "DB_APP": db_name, "DB_ALIAS": alias})

    if api is not None:
        if category != "frontend":
            raise BlueprintError(
                "api= es para frontends (la URL de la API queda en su build). Para que un servicio hable con "
                "otro, créalo y luego usa link_apps."
            )
        api_name = str(api.get("name") or "")
        public_url = ((api.get("domain") or {}).get("urls") or {}).get("prod")
        if not public_url:
            # El frontend corre en el navegador de quien lo abre: una API interna no le llega.
            raise BlueprintError(
                f"La API '{api_name}' no es pública en prod y el navegador no llegaría a ella. "
                "Hazla pública primero (set_exposure) o crea el frontend sin api=."
            )
        template_config.update({"API_URL": public_url, "API_APP": api_name})

    payload["template_config"] = template_config
    return payload
