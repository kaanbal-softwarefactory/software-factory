"""Qué dispositivos de la tailnet no se tocan al limpiar huérfanos.

La limpieza borra los dispositivos de Tailscale que no pertenecen a ninguna app.
Hay dispositivos que nunca deben caer ahí: el operador de Kubernetes, Vault y, en
cada instalación, las máquinas de las propias personas (su portátil, su PC).

Los dos primeros son de la plataforma y van fijos. Los demás son de cada
instalación, así que se declaran en su configuración
(`system_config.tailscale_protected_prefixes`) y no en el código: un nombre de
máquina escrito aquí protegería la de una sola persona y a las demás no.

Es un prefijo y no un nombre exacto porque Tailscale renombra los duplicados
(`equipo`, `equipo-1`, `equipo-2`): una coincidencia exacta dejaría sin proteger
justo el que aparece tras reinstalar.
"""

from typing import Any, Iterable, Mapping, Optional, Tuple

DEFAULT_PROTECTED_PREFIXES: Tuple[str, ...] = ("tailscale-operator", "vault-")

MAX_PREFIX_LENGTH = 63  # el límite de una etiqueta DNS


def configured_prefixes(config: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    """Prefijos protegidos que declara la instalación, ya limpios.

    Acepta una lista o un texto separado por comas. Ignora lo vacío: un prefijo
    vacío coincide con todos los dispositivos y volvería inútil la limpieza.
    """
    raw = (config or {}).get("tailscale_protected_prefixes") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    prefixes = []
    for item in raw if isinstance(raw, Iterable) else []:
        text = str(item).strip()
        if text and len(text) <= MAX_PREFIX_LENGTH and text not in prefixes:
            prefixes.append(text)
    return tuple(prefixes)


def protected_prefixes(config: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    """Los de la plataforma más los de la instalación."""
    return DEFAULT_PROTECTED_PREFIXES + tuple(
        p for p in configured_prefixes(config) if p not in DEFAULT_PROTECTED_PREFIXES
    )


def is_protected(hostname: str, config: Optional[Mapping[str, Any]]) -> bool:
    return any(hostname.startswith(prefix) for prefix in protected_prefixes(config))
