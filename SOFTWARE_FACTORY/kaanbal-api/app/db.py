import re

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client: AsyncIOMotorClient = None
db = None


def redacted(uri: str) -> str:
    """La URI sin la contraseña.

    El mensaje de conexión queda en el log de la API, y ese log lo lee cualquiera
    con acceso a los logs (la consola los muestra): con la contraseña adentro,
    cualquiera de ellos tenía la llave de la base de la plataforma.
    """
    return re.sub(r"://([^:/@\s]+):[^@\s]+@", r"://\1:****@", uri or "")


async def connect_db():
    global client, db
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client.forge
    print(f"Connected to MongoDB: {redacted(settings.mongodb_uri)}")


async def close_db():
    global client
    if client:
        client.close()
        print("Disconnected from MongoDB")


def get_db():
    return db
