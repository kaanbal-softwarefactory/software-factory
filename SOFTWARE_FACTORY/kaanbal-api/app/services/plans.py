"""
Planes: ver antes de hacer
==========================

Lo que crea algo o cambia lo que se ve en internet se pide dos veces. La primera
(dry_run) devuelve el plan —qué se crea, qué URLs cambian, qué variables llegan—
y un plan_id. La segunda, con ese plan_id, lo aplica: la API recalcula el plan y
solo sigue si sale idéntico. Si algo cambió entre medias (otra app tomó el
nombre, la app se mudó de dominio), el plan_id ya no coincide y no se toca nada.

El plan_id es una huella del plan, no un registro: no hay nada guardado que
caduque ni que limpiar, y la misma petición sobre el mismo estado da el mismo id.
La consola no lo manda y aplica directo, como siempre; el MCP lo exige.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional

PLAN_ID_LENGTH = 16


class PlanMismatch(ValueError):
    """El plan que se quiere aplicar ya no es el que se mostró."""


def plan_id(kind: str, plan: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"kind": kind, "plan": plan},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:PLAN_ID_LENGTH]


def verify(kind: str, plan: Mapping[str, Any], given: Optional[str]) -> None:
    """Sin plan_id no hay nada que comparar: así aplica la consola."""
    if not given:
        return
    if given != plan_id(kind, plan):
        raise PlanMismatch(
            "El plan cambió desde que lo viste (otra app tomó un nombre o un host, o la app cambió "
            "de estado). Pide el plan de nuevo, revísalo y aplica con el plan_id nuevo."
        )


def dry_run_answer(kind: str, plan: Mapping[str, Any], *, notices: Optional[List[str]] = None) -> Dict[str, Any]:
    """Respuesta de un dry_run: el plan, su id y nada aplicado.

    `notices` son avisos del momento ("ya hay un stack lanzándose"): se muestran,
    pero no entran en la huella, porque dejan de ser ciertos sin que el plan cambie.
    """
    answer = {"dry_run": True, "kind": kind, "plan": dict(plan), "plan_id": plan_id(kind, plan)}
    if notices:
        answer["notices"] = list(notices)
    return answer
