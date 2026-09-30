"""Confirmation point for sensitive actions; a future TOTP check belongs here."""
import time
from datetime import datetime, timedelta

from fastapi import HTTPException
from app.db import get_db


async def confirm(principal, username: str, password: str, *, action: str):
    if principal.via_token or username != principal.username or not password:
        raise HTTPException(403, "Confirma con el usuario y contraseña de tu propia sesión de administrador.")
    db = get_db()
    # Atomic, shared across API replicas; never log or store the submitted password.
    collection = db["step_up_attempts"]
    await collection.create_index("expires_at", expireAfterSeconds=0)
    attempt = await collection.find_one_and_update(
        {"_id": f"{principal.username}:{int(time.time()) // 300}"},
        {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": datetime.utcnow() + timedelta(minutes=10)}},
        upsert=True, return_document=True,
    )
    if attempt["count"] > 5:
        raise HTTPException(429, "Demasiados intentos de confirmación. Espera cinco minutos.")
    from app.routers.auth import verify_password
    user = await db.users.find_one({"username": principal.username, "disabled": {"$ne": True}})
    if not user or not verify_password(password, user.get("hashed_password", "")):
        raise HTTPException(403, "No se pudo confirmar la identidad del administrador.")
    # Reserve this shared step for a verified TOTP assertion when MFA is enabled.
    return {"method": "password", "action": action, "confirmed_at": datetime.utcnow()}
