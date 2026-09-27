"""
Variables de entorno de una app
===============================

Una app nueva suele pedir algo que nadie le inyecta (ADMIN_PASSWORD, la clave
de un servicio externo…) y hasta ahora la única forma de dársela era editar a
mano su overlay en infra-gitops. Esto la agrega por el mismo camino que usa la
plataforma para los vínculos de base: el secretGenerator del overlay, que
ArgoCD aplica y que reinicia la app con la variable nueva.

Tres reglas: el valor nunca vuelve en una respuesta (salvo uno recién generado
que la persona pide ver una sola vez, como un token personal: una contraseña de
administrador que nadie puede leer no sirve); una variable existente no se pisa
sin pedirlo; y las que escribe la plataforma (la conexión a la base) no se tocan
por aquí, porque romperían el vínculo.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from app.services import db_env

NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
MAX_VALUE_LENGTH = 4096
GENERATED_LENGTH = 32
SECRET_HINT = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|SALT)")

# Además de los nombres de conexión de las bases, la plataforma genera esta.
PLATFORM_OWNED = frozenset({"APP_SECRET"})

CREATED, UPDATED, UNCHANGED = "creada", "actualizada", "sin_cambios"


class VariableError(ValueError):
    """Petición que no se puede aplicar; el mensaje es para la persona."""


def looks_secret(name: str) -> bool:
    return bool(SECRET_HINT.search(name))


def generate_value(length: int = GENERATED_LENGTH) -> str:
    return secrets.token_urlsafe(length)[:length]


def managed_names(literals: Mapping[str, Any]) -> Set[str]:
    """Variables que escribe la plataforma en esta app y que no se editan por aquí."""
    names: Set[str] = set(db_env.CANONICAL_NAMES) | set(PLATFORM_OWNED)
    for key, value in literals.items():
        for suffix in ("_URI", "_URL"):
            if key.endswith(suffix) and key not in db_env.CANONICAL_NAMES and db_env.engine_from_uri(value):
                prefix = key[: -len(suffix)]
                names.update(k for k in literals if k.startswith(f"{prefix}_"))
    return names


def _check_value(value: str) -> None:
    # Va como línea `- NOMBRE=valor` de un YAML sin comillas: lo que YAML leería como
    # comentario o como otra estructura cambiaría el valor en silencio.
    if not value:
        raise VariableError("El valor está vacío. Escribe uno o usa generate para crear uno seguro.")
    if len(value) > MAX_VALUE_LENGTH:
        raise VariableError(f"El valor es demasiado largo (máximo {MAX_VALUE_LENGTH} caracteres).")
    if any(ch in value for ch in "\r\n\t\x00"):
        raise VariableError("El valor no puede tener saltos de línea ni tabuladores.")
    if value != value.strip():
        raise VariableError("El valor no puede empezar ni terminar con espacios.")
    if " #" in value or ": " in value or value.endswith(":"):
        raise VariableError("El valor no puede contener ' #' ni ': ', ni terminar en ':'.")


@dataclass
class VariableRequest:
    value: str
    generated: bool
    overwrite: bool
    environments: Optional[List[str]]
    reveal: bool


def resolve(variable: str, body: Mapping[str, Any]) -> VariableRequest:
    """Una petición validada, o VariableError con el motivo."""
    if not NAME.match(variable or ""):
        raise VariableError("El nombre debe ir en mayúsculas: letras, dígitos y guion bajo (ej. ADMIN_PASSWORD).")

    generate = bool(body.get("generate"))
    raw = body.get("value")
    if generate and raw not in (None, ""):
        raise VariableError("Usa value o generate, no los dos.")
    if generate:
        value = generate_value()
    else:
        if raw is None:
            raise VariableError("Falta el valor. Escribe uno o usa generate para crear uno seguro.")
        value = str(raw)
        _check_value(value)

    environments = body.get("environments")
    if environments is not None:
        if not isinstance(environments, list) or not all(isinstance(e, str) and e for e in environments):
            raise VariableError("environments debe ser una lista de nombres de ambiente.")
    return VariableRequest(
        value=value,
        generated=generate,
        overwrite=bool(body.get("overwrite")),
        environments=environments,
        # Solo lo generado se puede ver, y solo en la respuesta que lo crea.
        reveal=generate and bool(body.get("reveal")),
    )


def plan(literals: Mapping[str, str], variable: str, value: str, *, overwrite: bool) -> Tuple[str, Dict[str, str]]:
    """Qué pasaría con las variables de un ambiente: (estado, variables nuevas)."""
    if variable in managed_names(literals):
        raise VariableError(
            f"{variable} la gestiona la plataforma (conexión a la base o clave propia): no se cambia a mano. "
            "Si falta la conexión, usa 'Reconectar base de datos'."
        )
    current = dict(literals)
    if variable in current:
        if current[variable] == value:
            return UNCHANGED, current
        if not overwrite:
            raise VariableError(f"{variable} ya existe. Para reemplazar su valor, pide overwrite.")
        current[variable] = value
        return UPDATED, current
    current[variable] = value
    return CREATED, current
