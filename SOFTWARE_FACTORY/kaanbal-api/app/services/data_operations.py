"""
Respaldos, restauración y consultas de solo lectura de las bases de las apps
===========================================================================

Las bases que lanza Kaanbal (plantillas `postgres` y `mongodb`) corren con la
imagen oficial, que ya trae sus herramientas: pg_dump / pg_restore / psql y
mongodump / mongorestore / mongosh. Todo se hace ejecutando esas herramientas
dentro del pod de la base, con las credenciales que el pod ya tiene en su
entorno: la API nunca lee ni transporta la contraseña.

- **Respaldo**: el volcado sale del pod en base64 (stdout separado de stderr) y
  se guarda en GridFS de la base de la plataforma, fuera del disco de la app.
  Así sobrevive aunque se borre la app o su volumen. Se guardan los últimos
  `KEEP` por app y ambiente. Corre en segundo plano.
- **Restaurar**: primero toma un respaldo de seguridad del estado actual y
  luego reemplaza los datos con el respaldo elegido. Pide plan y, desde un
  token, aprobación humana.
- **Consultar**: una sentencia de lectura (Postgres, en transacción de solo
  lectura y con tiempo límite) o un find acotado (MongoDB). Sin escrituras.

El contenido del usuario (SQL, filtros) nunca se interpola en el shell: viaja
en base64, cuyo alfabeto no tiene nada que el shell interprete.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

COLLECTION = "data_operations"
BUCKET = "data_backups"
KEEP = 10
MAX_BACKUP_BYTES = 200 * 1024 * 1024
DUMP_SECONDS = 900
QUERY_SECONDS = 25
QUERY_OUTPUT = 64 * 1024
MAX_ROWS = 200

ENGINES = {"postgres": "postgres", "postgresql": "postgres", "mongodb": "mongodb", "mongo": "mongodb"}

_SQL_START = re.compile(r"^\s*(select|with|show|explain|table|values)\b", re.I)
# Funciones que no escriben datos pero sí tocan el servidor o su disco.
_SQL_DENY = re.compile(
    r"\b(pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|pg_read_file|"
    r"pg_read_binary_file|pg_ls_dir|pg_stat_file|lo_import|lo_export|dblink\w*|set_config|"
    r"pg_sleep\w*|pg_promote|copy)\b", re.I)
_MONGO_DENY = {"$where", "$function", "$accumulator", "$out", "$merge"}
_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}$")


class DataError(ValueError):
    """La operación no se puede hacer así. El mensaje es para la persona."""


# ── Puro ─────────────────────────────────────────────────────────────────
def engine_of(app: Mapping[str, Any]) -> str:
    template = str(app.get("template") or "").lower()
    engine = ENGINES.get(template)
    if not engine:
        raise DataError(f"{app.get('name')} no es una base que Kaanbal sepa respaldar (plantillas: postgres, mongodb).")
    return engine


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


_PG_ENV = 'export PGPASSWORD="$POSTGRES_PASSWORD"; '
_MONGO_AUTH = '-u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin'


def dump_command(engine: str) -> str:
    if engine == "postgres":
        return _PG_ENV + 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc | base64 -w 0'
    return f"mongodump --quiet --archive --gzip {_MONGO_AUTH} | base64 -w 0"


def restore_command(engine: str, size: int) -> str:
    """`head -c` lee exactamente lo enviado: el exec de Kubernetes no cierra stdin."""
    feed = f"head -c {int(size)} | base64 -d"
    if engine == "postgres":
        return _PG_ENV + f'{feed} | pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner'
    return f"{feed} | mongorestore --quiet --archive --gzip --drop {_MONGO_AUTH}"


def sql_statement(sql: str, limit: int) -> str:
    """Una sola sentencia de lectura, con tope de filas. Puro: lo prueba el test."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise DataError("Falta la consulta.")
    if len(text) > 8000:
        raise DataError("La consulta es demasiado larga (máximo 8000 caracteres).")
    if ";" in text:
        raise DataError("Una sola sentencia por consulta.")
    if not _SQL_START.match(text):
        raise DataError("Solo lectura: la consulta empieza con SELECT, WITH, SHOW, EXPLAIN, TABLE o VALUES.")
    denied = _SQL_DENY.search(text)
    if denied:
        raise DataError(f"{denied.group(1)} no está permitido en una consulta de solo lectura.")
    if re.match(r"^\s*(select|with|table|values)\b", text, re.I):
        return f"SELECT * FROM ({text}) AS kaanbal_query LIMIT {int(limit)}"
    return text


def sql_command(statement: str) -> str:
    options = f"-c default_transaction_read_only=on -c statement_timeout={QUERY_SECONDS * 1000 - 2000}"
    return (_PG_ENV + f"export PGOPTIONS='{options}'; echo {_b64(statement)} | base64 -d | "
            'psql -X -q --csv -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -')


def _deny_operators(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _MONGO_DENY:
                raise DataError(f"{key} no está permitido en una consulta de solo lectura.")
            _deny_operators(item)
    elif isinstance(value, list):
        for item in value:
            _deny_operators(item)


def mongo_request(operation: str, *, database: Optional[str] = None, collection: Optional[str] = None,
                  filter: Any = None, projection: Any = None, sort: Any = None, limit: int = 20) -> Dict[str, Any]:
    """Lo que se le pide a mongosh, validado. Puro: lo prueba el test."""
    if operation not in ("collections", "find", "count"):
        raise DataError("operation: collections, find o count.")
    for label, value in (("database", database), ("collection", collection)):
        if value is not None and not _NAME.match(str(value)):
            raise DataError(f"{label} no es un nombre válido.")
    if operation != "collections" and not collection:
        raise DataError("Falta collection.")
    for label, value in (("filter", filter), ("projection", projection), ("sort", sort)):
        if value is not None and not isinstance(value, dict):
            raise DataError(f"{label} debe ser un objeto JSON.")
    _deny_operators(filter)
    return {"op": operation, "database": database, "collection": collection, "filter": filter or {},
            "projection": projection or {}, "sort": sort or {}, "limit": max(1, min(int(limit), MAX_ROWS))}


_MONGO_SCRIPT = (
    "const q = EJSON.parse(Buffer.from('{payload}', 'base64').toString());"
    "const d = db.getSiblingDB(q.database || process.env.MONGO_INITDB_DATABASE || 'admin');"
    "let out;"
    "if (q.op === 'collections') {{ out = d.getCollectionNames(); }}"
    "else if (q.op === 'count') {{ out = d.getCollection(q.collection).countDocuments(q.filter); }}"
    "else {{ out = d.getCollection(q.collection).find(q.filter, q.projection).sort(q.sort).limit(q.limit).toArray(); }}"
    "print(EJSON.stringify(out, null, 0, {{relaxed: true}}));"
)


def mongo_command(request: Mapping[str, Any]) -> str:
    script = _MONGO_SCRIPT.format(payload=_b64(json.dumps(request)))
    return f'mongosh --quiet {_MONGO_AUTH} --eval "{script}"'


def csv_rows(text: str, limit: int) -> Dict[str, Any]:
    import csv
    import io

    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return {"columns": [], "rows": [], "row_count": 0}
    return {"columns": rows[0], "rows": rows[1:limit + 1], "row_count": len(rows) - 1}


def restore_plan(app: Mapping[str, Any], env: str, backup: Mapping[str, Any]) -> Dict[str, Any]:
    if backup.get("state") != "succeeded" or backup.get("kind") != "backup":
        raise DataError("Ese respaldo no está completo: elige uno con estado succeeded (list_backups).")
    if backup.get("app") != app.get("name"):
        raise DataError("Ese respaldo es de otra base.")
    return {
        "action": "restore", "app": app.get("name"), "env": env, "engine": backup.get("engine"),
        "backup": {"id": backup.get("_id"), "from_env": backup.get("env"), "created_at": str(backup.get("created_at")),
                   "size_bytes": backup.get("size"), "sha256": backup.get("sha256")},
        "effects": [
            "Primero se toma un respaldo de seguridad del estado actual (queda en list_backups).",
            f"Después se REEMPLAZAN los datos de {app.get('name')} en {env} por los del respaldo.",
            "Las apps conectadas siguen corriendo: pueden ver errores durante la restauración.",
        ],
    }


def public(doc: Mapping[str, Any]) -> Dict[str, Any]:
    view = {key: doc.get(key) for key in ("kind", "app", "env", "engine", "state", "size", "sha256", "actor",
                                          "error", "backup_id", "safety_backup_id", "note")}
    view["id"] = doc.get("_id")
    for key in ("created_at", "finished_at"):
        value = doc.get(key)
        view[key] = value.isoformat() + "Z" if isinstance(value, datetime) else value
    return {key: value for key, value in view.items() if value not in (None, "")}


# ── Clúster ──────────────────────────────────────────────────────────────
def _pod(app: str, env: str):
    from app.services.autonomy_cluster import clients
    from app.services.autonomy_policy import resource_name

    resource_name(app)
    resource_name(env)
    if app.startswith("kaanbal-") or app in {"vault", "argocd", "datastore", "tailscale-operator"}:
        raise DataError("Los componentes de la plataforma no se respaldan ni se consultan por aquí.")
    core, _ = clients()
    pods = core.list_namespaced_pod(env, label_selector=f"app={app}").items
    running = [p for p in pods if p.status.phase == "Running" and not p.metadata.deletion_timestamp]
    if not running:
        raise DataError(f"{app} no tiene un pod corriendo en {env}.")
    pod = sorted(running, key=lambda p: p.metadata.name)[0]
    container = next((c.name for c in pod.spec.containers if c.name == app), pod.spec.containers[0].name)
    return core, pod.metadata.name, container


def run(app: str, env: str, command: str, *, seconds: int, stdin: str = "", limit: int = QUERY_OUTPUT) -> Dict[str, Any]:
    """Ejecuta en el pod de la base con stdout y stderr separados (el volcado no se mezcla con avisos)."""
    from kubernetes.stream import stream

    from app.services.autonomy_cluster import shell_command

    from kubernetes.client.rest import ApiException

    core, pod, container = _pod(app, env)
    try:
        ws = stream(core.connect_post_namespaced_pod_exec, pod, env, container=container,
                    command=shell_command(command, seconds), stderr=True, stdout=True, stdin=bool(stdin),
                    tty=False, _preload_content=False)
    except ApiException as exc:
        if exc.status == 403:
            raise DataError(f"La API no tiene permiso pods/exec en '{env}'. Respaldar y consultar bases requiere "
                            "concederlo por GitOps (ver docs/MCP_AUTONOMY.md, «Datos de las bases»).")
        raise
    out, err, size = [], [], 0
    deadline = time.monotonic() + seconds + 15
    try:
        for offset in range(0, len(stdin), 65536):
            ws.write_stdin(stdin[offset:offset + 65536])
        while ws.is_open() and time.monotonic() < deadline:
            ws.update(timeout=1)
            chunk = ws.read_stdout()
            if chunk:
                size += len(chunk)
                if size > limit:
                    raise DataError("La salida supera el tamaño permitido.")
                out.append(chunk)
            chunk = ws.read_stderr()
            if chunk and sum(map(len, err)) < 16384:
                err.append(chunk)
        timed_out = ws.is_open()
        code = None if timed_out else ws.returncode
    finally:
        ws.close()
    return {"stdout": "".join(out), "stderr": "".join(err)[-4000:], "exit_code": code, "timed_out": timed_out}


# ── Persistencia ─────────────────────────────────────────────────────────
def _bucket():
    from motor.motor_asyncio import AsyncIOMotorGridFSBucket

    from app.db import get_db

    return AsyncIOMotorGridFSBucket(get_db(), bucket_name=BUCKET)


def _operations():
    from app.db import get_db

    return get_db()[COLLECTION]


async def start(kind: str, app: Mapping[str, Any], env: str, actor: str, **extra: Any) -> Dict[str, Any]:
    doc = {"_id": uuid4().hex[:20], "kind": kind, "app": app["name"], "env": env, "engine": engine_of(app),
           "state": "running", "actor": actor, "created_at": datetime.utcnow(), **extra}
    await _operations().insert_one(doc)
    return doc


async def _finish(identifier: str, **fields: Any) -> None:
    await _operations().update_one({"_id": identifier}, {"$set": {**fields, "finished_at": datetime.utcnow()}})


async def backup(doc: Mapping[str, Any]) -> Dict[str, Any]:
    """Vuelca la base del pod y la guarda en GridFS. Devuelve el registro final."""
    import asyncio

    from app.services.diagnosis import mask

    try:
        result = await asyncio.to_thread(run, doc["app"], doc["env"], dump_command(doc["engine"]),
                                         seconds=DUMP_SECONDS, limit=MAX_BACKUP_BYTES * 4 // 3 + 4)
        if result["exit_code"] != 0:
            raise DataError(mask(result["stderr"].strip()[-500:]) or "El volcado terminó con error.")
        data = base64.b64decode(result["stdout"].strip() or b"", validate=True)
        if not data:
            raise DataError("El volcado salió vacío.")
        sha = hashlib.sha256(data).hexdigest()
        file_id = await _bucket().upload_from_stream(
            f"{doc['app']}-{doc['env']}-{doc['_id']}.dump", data,
            metadata={"app": doc["app"], "env": doc["env"], "engine": doc["engine"], "operation": doc["_id"]})
        await _finish(doc["_id"], state="succeeded", size=len(data), sha256=sha, file_id=file_id)
        await _prune(doc["app"], doc["env"])
    except Exception as exc:  # noqa: BLE001 — el registro tiene que terminar con el motivo
        await _finish(doc["_id"], state="failed", error=str(exc)[:500] if isinstance(exc, DataError) else type(exc).__name__)
    return public(await _operations().find_one({"_id": doc["_id"]}))


async def restore(doc: Mapping[str, Any], app: Mapping[str, Any], source: Mapping[str, Any]) -> Dict[str, Any]:
    """Respaldo de seguridad y luego restauración. Se detiene si el de seguridad falla."""
    import asyncio

    from app.services.diagnosis import mask

    safety = await start("backup", app, doc["env"], doc["actor"], note=f"seguridad antes de restaurar {source['_id']}")
    await _operations().update_one({"_id": doc["_id"]}, {"$set": {"safety_backup_id": safety["_id"]}})
    if (await backup(safety)).get("state") != "succeeded":
        await _finish(doc["_id"], state="failed", error="No se pudo tomar el respaldo de seguridad: no se tocó nada.")
        return public(await _operations().find_one({"_id": doc["_id"]}))
    try:
        stream = await _bucket().open_download_stream(source["file_id"])
        payload = base64.b64encode(await stream.read()).decode("ascii")
        result = await asyncio.to_thread(run, doc["app"], doc["env"], restore_command(doc["engine"], len(payload)),
                                         seconds=DUMP_SECONDS, stdin=payload)
        if result["exit_code"] != 0:
            raise DataError(mask(result["stderr"].strip()[-500:]) or "La restauración terminó con error.")
        await _finish(doc["_id"], state="succeeded")
    except Exception as exc:  # noqa: BLE001
        await _finish(doc["_id"], state="failed", error=(str(exc)[:500] if isinstance(exc, DataError) else type(exc).__name__)
                      + f" — el estado previo quedó en el respaldo {safety['_id']}.")
    return public(await _operations().find_one({"_id": doc["_id"]}))


async def query(app: Mapping[str, Any], env: str, request: Mapping[str, Any]) -> Dict[str, Any]:
    import asyncio

    from app.services.diagnosis import mask

    engine = engine_of(app)
    if engine == "postgres":
        limit = max(1, min(int(request.get("limit") or 50), MAX_ROWS))
        command = sql_command(sql_statement(str(request.get("sql") or ""), limit))
    else:
        limit = 0
        command = mongo_command(mongo_request(
            str(request.get("operation") or "find"), database=request.get("database"),
            collection=request.get("collection"), filter=request.get("filter"),
            projection=request.get("projection"), sort=request.get("sort"), limit=request.get("limit") or 20))
    result = await asyncio.to_thread(run, app["name"], env, command, seconds=QUERY_SECONDS, limit=QUERY_OUTPUT)
    if result["timed_out"]:
        raise DataError(f"La consulta superó {QUERY_SECONDS} s.")
    if result["exit_code"] != 0:
        raise DataError(mask(result["stderr"].strip()[-800:]) or "La consulta terminó con error.")
    output = "\n".join(mask(line) for line in result["stdout"].splitlines())
    if engine == "postgres":
        return {"engine": engine, "env": env, **csv_rows(output, limit)}
    try:
        data = json.loads(output or "null")
    except ValueError:
        data = output[:QUERY_OUTPUT]
    return {"engine": engine, "env": env, "result": data}


async def listing(app: str) -> List[Dict[str, Any]]:
    rows = await _operations().find({"app": app}).sort("created_at", -1).to_list(50)
    return [public(row) for row in rows]


async def find(app: str, identifier: str) -> Optional[Dict[str, Any]]:
    return await _operations().find_one({"_id": str(identifier), "app": app})


async def last_backup(app: str) -> Optional[Dict[str, Any]]:
    return await _operations().find_one({"app": app, "kind": "backup", "state": "succeeded"},
                                        sort=[("created_at", -1)])


async def _prune(app: str, env: str) -> None:
    old = await _operations().find({"app": app, "env": env, "kind": "backup", "state": "succeeded"}) \
        .sort("created_at", -1).skip(KEEP).to_list(100)
    for doc in old:
        try:
            await _bucket().delete(doc["file_id"])
        except Exception:  # noqa: BLE001 — si el archivo ya no está, igual se marca
            pass
        await _operations().update_one({"_id": doc["_id"]}, {"$set": {"state": "pruned"}, "$unset": {"file_id": ""}})


async def init_indexes() -> None:
    await _operations().create_index([("app", 1), ("created_at", -1)])
