"""Conexión a la base de datos, igual en local que en Kaanbal.

La base llega SIEMPRE por variables de entorno, nunca por una URL escrita en el
código. Kaanbal inyecta los nombres estándar del motor (MONGO_URI, DATABASE_URL,
PGHOST...) además de los que llevan el prefijo de la base vinculada, así que el
mismo código corre con el Mongo de tu docker-compose y con el del clúster.

El motor se deduce del esquema de la URI: mongodb:// o postgresql://. Si no hay
ninguna variable, se usa la de docker-compose.yml (localhost), para que
`uvicorn main:app --reload` funcione recién clonado el repositorio.
"""

import os
from typing import Any, Dict, List, Optional

APP_NAME = os.getenv("APP_NAME", "placeholder-app")
DB_NAME = os.getenv("DB_NAME") or APP_NAME.replace("-", "_")

# Orden de búsqueda: lo que inyecta Kaanbal primero, el default local al final.
MONGO_VARS = ("MONGO_URI", "MONGODB_URI", "MONGO_URL", "MONGODB_URL")
SQL_VARS = ("DATABASE_URL", "POSTGRES_URI", "POSTGRES_URL")
LOCAL_MONGO = "mongodb://localhost:27017"
LOCAL_POSTGRES = "postgresql://postgres:postgres@localhost:5432/postgres"


def database_url() -> str:
    """URI de la base: la que inyectó Kaanbal, o la local de docker-compose."""
    for name in (*MONGO_VARS, *SQL_VARS):
        value = os.getenv(name)
        if value:
            return value
    # Sin variables: desarrollo local recién clonado.
    return LOCAL_MONGO if os.getenv("DB_ENGINE", "mongodb") == "mongodb" else LOCAL_POSTGRES


def engine_of(uri: str) -> str:
    scheme = uri.split("://", 1)[0].lower()
    if scheme.startswith("mongodb"):
        return "mongodb"
    if scheme in ("postgresql", "postgres"):
        return "postgres"
    raise RuntimeError(f"No sé hablar con '{scheme}://'. Usa mongodb:// o postgresql://.")


class Store:
    """Acceso mínimo a datos. Sustitúyelo por tu modelo cuando crezca la app.

    `init()` es lo que hace que la primera vez funcione: crea la base, la
    colección o la tabla y su índice. Es idempotente, así que corre en cada
    arranque —local y en el clúster— sin romper nada.
    """

    def __init__(self, uri: Optional[str] = None):
        self.uri = uri or database_url()
        self.engine = engine_of(self.uri)
        self._client = None
        self._conn = None

    # ── Arranque ─────────────────────────────────────────────────────────
    def init(self) -> None:
        if self.engine == "mongodb":
            from pymongo import MongoClient

            self._client = MongoClient(self.uri, serverSelectionTimeoutMS=10000)
            # Mongo crea base y colección al primer escribir; el índice las materializa.
            self._client[DB_NAME]["items"].create_index("name")
        else:
            import psycopg

            self._conn = psycopg.connect(self.uri, autocommit=True)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS items ("
                " id SERIAL PRIMARY KEY,"
                " name TEXT NOT NULL,"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        if self._conn is not None:
            self._conn.close()

    # ── Uso ──────────────────────────────────────────────────────────────
    def ping(self) -> bool:
        try:
            if self.engine == "mongodb":
                self._client.admin.command("ping")
            else:
                self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def add_item(self, name: str) -> Dict[str, Any]:
        if self.engine == "mongodb":
            result = self._client[DB_NAME]["items"].insert_one({"name": name})
            return {"id": str(result.inserted_id), "name": name}
        row = self._conn.execute(
            "INSERT INTO items (name) VALUES (%s) RETURNING id", (name,)
        ).fetchone()
        return {"id": row[0], "name": name}

    def list_items(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self.engine == "mongodb":
            return [
                {"id": str(doc["_id"]), "name": doc.get("name", "")}
                for doc in self._client[DB_NAME]["items"].find().limit(limit)
            ]
        rows = self._conn.execute(
            "SELECT id, name FROM items ORDER BY id DESC LIMIT %s", (limit,)
        ).fetchall()
        return [{"id": row[0], "name": row[1]} for row in rows]
