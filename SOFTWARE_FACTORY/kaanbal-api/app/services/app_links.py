"""
Vincular una app con otra
=========================

Un vínculo le da a una app las variables para hablar con otra, por el mismo
camino que ya usan las bases al crear una app: el secretGenerator de su overlay
en infra-gitops, que ArgoCD aplica reiniciando la app.

- Con una base (Mongo, Postgres, MySQL, Redis): sus credenciales con el prefijo
  del vínculo (TIENDA_DB_URI, TIENDA_DB_USER…) y los nombres estándar del motor
  (MONGO_URI, DATABASE_URL…), lo mismo que recibe una app creada ya vinculada.
- Con cualquier otra app: dónde encontrarla dentro del clúster (PAGOS_API_HOST,
  PAGOS_API_PORT, PAGOS_API_URL). Es tráfico interno: no pasa por internet ni
  depende de cómo esté expuesta la otra app.

Tres reglas. Un nombre con el prefijo del vínculo que ya existe con otro valor no
se pisa: el vínculo se rechaza y se explica. Los demás nombres (los estándar del
motor) solo se agregan si faltan. Y se recuerda qué agregó cada vínculo, para
poder quitarlo después sin tocar nada más.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from app.services import db_env, link_service

KIND_DATABASE = "database"
KIND_SERVICE = "service"

ALIAS = re.compile(r"^[A-Z][A-Z0-9_]{0,47}$")

# Una base sin contraseña en estos motores es una base cuyas credenciales no se
# encontraron (Vault sellado y sin Secret en el clúster): vincularla así rompería la app.
ENGINES_WITH_PASSWORD = frozenset({"mongodb", "postgres", "mysql"})


class LinkError(ValueError):
    """El vínculo no se puede hacer así; el mensaje es para la persona."""


def kind_of(provider: Mapping) -> str:
    if db_env.engine_from_template(provider.get("template")) or provider.get("category") == "database":
        return KIND_DATABASE
    return KIND_SERVICE


def alias_for(provider_name: str, alias: Optional[str] = None) -> str:
    value = str(alias or link_service.default_alias(provider_name)).strip().upper()
    if not ALIAS.match(value):
        raise LinkError(
            f"'{alias}' no sirve como prefijo de variables: mayúsculas, dígitos y guion bajo, empezando por letra."
        )
    return value


def environments_for(consumer: Mapping, provider: Mapping, requested: Optional[Iterable[str]] = None) -> List[str]:
    """Cada ambiente de la app se conecta al mismo ambiente de la otra."""
    consumer_envs = list(consumer.get("environments") or ["prod"])
    provider_envs = list(provider.get("environments") or ["prod"])
    if requested:
        wanted = list(dict.fromkeys(str(env).strip().lower() for env in requested if str(env).strip()))
        missing_here = [env for env in wanted if env not in consumer_envs]
        if missing_here:
            raise LinkError(f"'{consumer.get('name')}' no tiene el ambiente {', '.join(missing_here)}.")
        missing_there = [env for env in wanted if env not in provider_envs]
        if missing_there:
            raise LinkError(
                f"'{provider.get('name')}' no tiene el ambiente {', '.join(missing_there)}: cada ambiente se "
                "conecta al mismo ambiente de la otra app."
            )
        return wanted
    common = [env for env in consumer_envs if env in provider_envs]
    if not common:
        raise LinkError(
            f"'{consumer.get('name')}' ({', '.join(consumer_envs)}) y '{provider.get('name')}' "
            f"({', '.join(provider_envs)}) no comparten ningún ambiente."
        )
    return common


def check_pair(consumer: Mapping, provider: Mapping) -> None:
    if consumer.get("name") == provider.get("name"):
        raise LinkError("Una app no se vincula consigo misma.")
    if kind_of(consumer) == KIND_DATABASE:
        raise LinkError(
            f"'{consumer.get('name')}' es una base de datos: el vínculo va al revés (la app que la usa → la base)."
        )


def service_variables(provider_name: str, env: str, alias: str, port: int, port_name: str = "http") -> Dict[str, str]:
    """{ALIAS}_HOST / _PORT / _URL para llegar a otra app por la red del clúster."""
    literals = link_service.build_env_literals({
        "to_app": provider_name, "to_env": env, "alias": alias,
        "port_number": port, "port_name": port_name,
    })
    return dict(item.split("=", 1) for item in literals)


def check_database_variables(provider_name: str, env: str, alias: str, engine: str, variables: Mapping[str, str]) -> None:
    if not variables or (engine in ENGINES_WITH_PASSWORD and not variables.get(f"{alias}_PASSWORD")):
        raise LinkError(
            f"No encontré las credenciales de '{provider_name}' en {env} (ni en Vault ni en el clúster). "
            "Revisa que la base haya terminado de desplegarse y que Vault esté abierto."
        )


def merge(literals: Mapping[str, str], wanted: Mapping[str, str], alias: str) -> Tuple[Dict[str, str], List[str], List[str]]:
    """(variables nuevas del overlay, nombres agregados, nombres que ya estaban).

    Los nombres con el prefijo del vínculo son suyos: si ya existen con otro valor,
    otra cosa los usa y no se pisan. Los demás (MONGO_URI, DATABASE_URL…) son
    convenciones compartidas: se agregan si faltan y, si ya están, se respetan.
    """
    prefix = f"{alias}_"
    current = dict(literals)
    added: List[str] = []
    kept: List[str] = []
    conflicts: List[str] = []
    for name, value in wanted.items():
        if name not in current:
            current[name] = value
            added.append(name)
        elif current[name] == value or not name.startswith(prefix):
            kept.append(name)
        else:
            conflicts.append(name)
    if conflicts:
        raise LinkError(
            f"La app ya tiene {', '.join(sorted(conflicts))} con otro valor. Usa otro prefijo (alias) "
            "o quita primero el vínculo que las puso."
        )
    return current, sorted(added), sorted(kept)


def remove(literals: Mapping[str, str], names: Iterable[str]) -> Tuple[Dict[str, str], List[str]]:
    """Quitar lo que puso un vínculo. Lo que ya no está no es un error."""
    current = dict(literals)
    removed = sorted({name for name in names if name in current})
    for name in removed:
        del current[name]
    return current, removed
