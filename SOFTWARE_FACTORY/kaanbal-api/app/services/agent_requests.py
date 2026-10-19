"""
Secretos que pide un agente y captura una persona
=================================================

Un agente nunca debe ver ni escribir el valor de una credencial real (la clave
de un proveedor de pagos, el token de un servicio externo): si la escribe, queda
en su contexto, en el chat y quizá en un log. Tampoco tiene sentido que lo
invente con generate=true cuando el valor lo emite un tercero.

Entonces la pide: `request_secret` deja una solicitud con la app, el nombre de
la variable y para qué hace falta. Una persona la ve en la consola (Acceso →
Solicitudes), pega el valor en un campo de contraseña y la plataforma lo guarda
como cualquier otra variable de la app. El agente solo sabe que ya está.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from app.services.autonomy_policy import redact

COLLECTION = "secret_requests"
TTL_HOURS = 72
VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

PENDING, FULFILLED, CANCELLED, EXPIRED = "pending", "fulfilled", "cancelled", "expired"


class RequestError(ValueError):
    pass


def validate(variable: str, reason: str, environments: Optional[List[str]], available: List[str]) -> List[str]:
    """Lo que se puede pedir. Puro: lo prueba el test."""
    if not VARIABLE.match(variable or ""):
        raise RequestError(f"'{variable}' no es un nombre de variable válido: mayúsculas, dígitos y guion bajo.")
    if len((reason or "").strip()) < 5:
        raise RequestError("Explica en reason para qué hace falta (la persona que la captura lo lee).")
    wanted = list(environments or available)
    unknown = [env for env in wanted if env not in available]
    if unknown:
        raise RequestError(f"La app no tiene ambiente(s): {', '.join(unknown)}.")
    return wanted


def public(doc: Mapping[str, Any]) -> Dict[str, Any]:
    view = {key: doc.get(key) for key in ("app", "variable", "environments", "reason", "state",
                                          "requested_by", "token_name", "fulfilled_by")}
    view["id"] = doc.get("_id")
    for key in ("created_at", "expires_at", "fulfilled_at"):
        value = doc.get(key)
        view[key] = value.isoformat() + "Z" if isinstance(value, datetime) else value
    return {key: value for key, value in view.items() if value not in (None, "", [])}


async def create(principal, app: Mapping[str, Any], variable: str, reason: str,
                 environments: Optional[List[str]] = None) -> Dict[str, Any]:
    from app.db import get_db

    wanted = validate(variable, reason, environments, list(app.get("environments") or ["prod"]))
    collection = get_db()[COLLECTION]
    now = datetime.utcnow()
    existing = await collection.find_one({"app": app["name"], "variable": variable, "state": PENDING,
                                          "expires_at": {"$gt": now}})
    if existing:
        return {**public(existing), "message": "Ya había una solicitud pendiente para esa variable."}
    doc = {
        "_id": uuid4().hex[:20], "app": app["name"], "variable": variable, "environments": wanted,
        "reason": redact(reason)[:500], "requested_by": principal.username, "token_name": principal.token_name,
        "state": PENDING, "created_at": now, "expires_at": now + timedelta(hours=TTL_HOURS),
    }
    await collection.insert_one(doc)
    return {**public(doc), "message": "Solicitud creada. Una persona captura el valor en la consola, en "
                                      "Acceso → Solicitudes; consulta su estado con list_secret_requests."}


async def for_app(app_name: str) -> List[Dict[str, Any]]:
    from app.db import get_db

    await _expire()
    rows = await get_db()[COLLECTION].find({"app": app_name}).sort("created_at", -1).to_list(50)
    return [public(row) for row in rows]


async def listing(state: Optional[str] = None) -> List[Dict[str, Any]]:
    from app.db import get_db

    await _expire()
    query = {"state": state} if state else {}
    rows = await get_db()[COLLECTION].find(query).sort("created_at", -1).to_list(100)
    return [public(row) for row in rows]


async def claim(identifier: str) -> Dict[str, Any]:
    """La solicitud pendiente, o por qué ya no se puede atender."""
    from app.db import get_db

    doc = await get_db()[COLLECTION].find_one({"_id": str(identifier)})
    if not doc:
        raise RequestError("La solicitud no existe.")
    if doc["state"] != PENDING or doc["expires_at"] <= datetime.utcnow():
        raise RequestError("La solicitud ya se atendió, se canceló o venció.")
    return doc


async def close(identifier: str, *, state: str, actor: str) -> Dict[str, Any]:
    from app.db import get_db

    doc = await get_db()[COLLECTION].find_one_and_update(
        {"_id": str(identifier), "state": PENDING},
        {"$set": {"state": state, "fulfilled_by": actor, "fulfilled_at": datetime.utcnow()}},
        return_document=True,
    )
    if not doc:
        raise RequestError("La solicitud ya se atendió, se canceló o venció.")
    return public(doc)


async def _expire() -> None:
    from app.db import get_db

    await get_db()[COLLECTION].update_many({"state": PENDING, "expires_at": {"$lte": datetime.utcnow()}},
                                           {"$set": {"state": EXPIRED}})


async def init_indexes() -> None:
    from app.db import get_db

    collection = get_db()[COLLECTION]
    await collection.create_index([("app", 1), ("variable", 1), ("state", 1)])
    await collection.create_index("created_at", expireAfterSeconds=30 * 86400)
