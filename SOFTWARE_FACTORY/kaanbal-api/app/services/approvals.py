"""
Aprobación humana para lo irreversible
======================================

Un token crítico prueba que alguien confirmó su contraseña al emitirlo, pero no
que una persona esté mirando cuando el agente decide ejecutar algo como root,
restaurar una base o borrar una app. Para eso existe esta cola.

Cuando un agente (siempre llega con token) pide una de esas acciones sin
aprobación, la API no la ejecuta: deja una solicitud pendiente con la acción, el
recurso y un resumen legible, y responde 428 con su id. Una persona la revisa en
la consola (Acceso → Solicitudes), confirma su contraseña y la aprueba o rechaza.
El agente repite la llamada con ese `approval_id`; la API vuelve a calcular la
huella de la acción y solo sigue si es exactamente la aprobada. Cada aprobación
se usa una vez y vence a los 30 minutos.

Quien opera desde la consola con su sesión ya es la persona: no pasa por aquí.
La política de autonomía puede apagar la cola (`approval_required: false`), por
ejemplo en una célula de laboratorio; por defecto está encendida.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from app.services.autonomy_policy import AutonomyError, redact

COLLECTION = "autonomy_approvals"
TTL_MINUTES = 30
SUMMARY_LIMIT = 4000

PENDING, APPROVED, REJECTED, USED = "pending", "approved", "rejected", "used"

# Lo que exige aprobación y cómo se le explica a la persona que decide.
ACTIONS: Dict[str, str] = {
    "app.execute": "Ejecutar un comando dentro de una app",
    "host.execute": "Ejecutar un comando como root en un nodo",
    "workspace.merge": "Integrar un PR en la rama que despliega",
    "core.upgrade": "Actualizar el core de la plataforma",
    "data.restore": "Restaurar una base de datos (reemplaza sus datos)",
    "app.delete": "Eliminar una app con su repositorio, secretos y despliegues",
}


def _collection():
    """La colección de solicitudes. Un solo punto de acceso: los contratos lo simulan."""
    from app.db import get_db

    return get_db()[COLLECTION]


class ApprovalRequired(AutonomyError):
    """La acción espera a una persona. El mensaje dice cómo seguir."""

    def __init__(self, approval: Mapping[str, Any]):
        self.approval = dict(approval)
        super().__init__(
            f"Esta acción requiere aprobación humana. Quedó registrada como approval_id={approval['_id']} "
            f"({ACTIONS.get(approval['action'], approval['action'])} sobre {approval['target']}). Pídele a una "
            "persona que la apruebe en la consola, en Acceso → Solicitudes; después repite exactamente la misma "
            f"llamada con approval_id=\"{approval['_id']}\". Vence en {TTL_MINUTES} minutos.",
            428,
        )


def fingerprint(action: str, target: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps({"action": action, "target": target, "payload": payload},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def required_by(policy: Optional[Mapping[str, Any]]) -> bool:
    """Encendida salvo que el owner la apague explícitamente."""
    return (policy or {}).get("approval_required", True) is not False


def public(doc: Mapping[str, Any]) -> Dict[str, Any]:
    view = {key: doc.get(key) for key in ("action", "target", "summary", "reason", "state", "actor",
                                          "token_name", "decided_by", "decision_note")}
    view["id"] = doc.get("_id")
    view["label"] = ACTIONS.get(doc.get("action"), doc.get("action"))
    for key in ("created_at", "expires_at", "decided_at", "used_at"):
        value = doc.get(key)
        view[key] = value.isoformat() + "Z" if isinstance(value, datetime) else value
    return {key: value for key, value in view.items() if value not in (None, "")}


def check(doc: Optional[Mapping[str, Any]], digest: str, now: datetime) -> None:
    """Por qué una aprobación no sirve para esta llamada. Puro: lo prueba el test."""
    if not doc:
        raise AutonomyError("Aprobación no encontrada para este token.", 404)
    if doc.get("digest") != digest:
        raise AutonomyError("Esa aprobación es para otra acción o con otros argumentos. Repite la llamada "
                            "exactamente como se aprobó, o pide una aprobación nueva.", 409)
    if doc.get("expires_at") and doc["expires_at"] <= now:
        raise AutonomyError("La aprobación venció. Pide una nueva repitiendo la llamada sin approval_id.", 410)
    state = doc.get("state")
    if state == PENDING:
        raise AutonomyError(f"La aprobación {doc['_id']} sigue pendiente: una persona tiene que aprobarla en "
                            "Acceso → Solicitudes.", 428)
    if state == REJECTED:
        note = f" Motivo: {doc['decision_note']}" if doc.get("decision_note") else ""
        raise AutonomyError(f"Una persona rechazó esta acción.{note}", 403)
    if state == USED:
        raise AutonomyError("Esa aprobación ya se usó. Cada aprobación sirve una sola vez.", 409)
    if state != APPROVED:
        raise AutonomyError("La aprobación no está vigente.", 409)


async def require(principal, *, action: str, target: str, payload: Mapping[str, Any], summary: str,
                  reason: str = "", approval_id: Optional[str] = None,
                  policy: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Deja pasar a una persona en la consola; a un token, solo con su aprobación vigente."""
    if not principal.via_token or not required_by(policy):
        return None
    collection = _collection()
    digest = fingerprint(action, target, payload)
    now = datetime.utcnow()
    if approval_id:
        doc = await collection.find_one({"_id": str(approval_id), "credential_id": principal.token_id})
        check(doc, digest, now)
        used = await collection.find_one_and_update(
            {"_id": doc["_id"], "state": APPROVED},
            {"$set": {"state": USED, "used_at": now}}, return_document=True,
        )
        if not used:
            raise AutonomyError("Esa aprobación ya se usó. Cada aprobación sirve una sola vez.", 409)
        return public(used)

    # La misma petición repetida no llena la cola: reaprovecha la pendiente.
    existing = await collection.find_one({"credential_id": principal.token_id, "digest": digest,
                                          "state": PENDING, "expires_at": {"$gt": now}})
    if existing:
        raise ApprovalRequired(existing)
    doc = {
        "_id": uuid4().hex[:20], "action": action, "target": target, "digest": digest,
        "summary": redact(summary)[:SUMMARY_LIMIT], "reason": redact(reason)[:500],
        "actor": principal.username, "credential_id": principal.token_id, "token_name": principal.token_name,
        "state": PENDING, "created_at": now, "expires_at": now + timedelta(minutes=TTL_MINUTES),
    }
    await collection.insert_one(doc)
    raise ApprovalRequired(doc)


async def gate(request, *, action: str, target: str, payload: Mapping[str, Any], summary: str,
               reason: str = "", approval_id: Optional[str] = None, elevated: bool = True) -> Optional[Dict[str, Any]]:
    """Lo mismo que `require`, para los routers que responden HTTPException.

    Con un token, además exige que sea crítico: lo irreversible no se hace con un
    token de uso diario aunque alguien lo apruebe.
    """
    from fastapi import HTTPException

    from app.db import get_db
    from app.services.autonomy_policy import require_elevated

    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "Sesión no resuelta")
    try:
        if elevated:
            require_elevated(principal)
        config = await get_db().system_config.find_one({"_id": "main"}) or {}
        return await require(principal, action=action, target=target, payload=payload, summary=summary,
                             reason=reason, approval_id=approval_id, policy=config.get("autonomy"))
    except AutonomyError as exc:
        raise HTTPException(exc.status, str(exc))


async def listing(limit: int = 50) -> List[Dict[str, Any]]:
    collection = _collection()
    now = datetime.utcnow()
    await collection.update_many({"state": PENDING, "expires_at": {"$lte": now}}, {"$set": {"state": "expired"}})
    rows = await collection.find().sort("created_at", -1).to_list(max(1, min(limit, 200)))
    return [public(row) for row in rows]


async def get(principal, identifier: str) -> Dict[str, Any]:
    query: Dict[str, Any] = {"_id": str(identifier)}
    if not principal.can("autonomy.policy.manage"):
        query["credential_id"] = principal.token_id
        query["actor"] = principal.username
    doc = await _collection().find_one(query)
    if not doc:
        raise AutonomyError("Aprobación no encontrada.", 404)
    return public(doc)


async def decide(principal, identifier: str, *, approve: bool, note: str = "") -> Dict[str, Any]:
    now = datetime.utcnow()
    doc = await _collection().find_one_and_update(
        {"_id": str(identifier), "state": PENDING, "expires_at": {"$gt": now}},
        {"$set": {"state": APPROVED if approve else REJECTED, "decided_by": principal.username,
                  "decided_at": now, "decision_note": redact(note)[:500],
                  # Desde que se aprueba corre su propia ventana para usarla.
                  "expires_at": now + timedelta(minutes=TTL_MINUTES)}},
        return_document=True,
    )
    if not doc:
        raise AutonomyError("La solicitud no existe, ya se decidió o venció.", 409)
    return public(doc)


async def init_indexes() -> None:
    collection = _collection()
    await collection.create_index([("credential_id", 1), ("digest", 1), ("state", 1)])
    await collection.create_index("created_at", expireAfterSeconds=30 * 86400)
