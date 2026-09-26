"""
Nombres de las variables de una base vinculada
==============================================

Kaanbal inyecta las credenciales de cada base con el prefijo del nombre de la
app que la sirve: vincular 'north-star-bay-bd' produce NORTH_STAR_BAY_BD_URI,
NORTH_STAR_BAY_BD_HOST, etc. Ese nombre no lo puede adivinar quien escribe la
app —depende de cómo se llame la base en esta instalación—, así que un backend
con `os.environ['MONGO_URI']` arranca en CrashLoopBackOff aunque el vínculo
esté bien hecho.

Además de las variables con prefijo (que siguen siendo las canónicas y no
cambian), se publican los nombres convencionales de cada motor: MONGO_URI,
DATABASE_URL, PGHOST, REDIS_URL... Solo cuando no hay ambigüedad: si el
ambiente tiene dos bases del mismo motor, el nombre corto no sabría a cuál
apuntar y no se publica.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# Componente del vínculo → nombres que espera el ecosistema de cada motor.
# El orden importa solo para leerlo: todos apuntan al mismo valor.
ENGINE_ALIASES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "mongodb": {
        "URI": ("MONGO_URI", "MONGODB_URI", "MONGO_URL", "MONGODB_URL"),
        "HOST": ("MONGO_HOST",),
        "PORT": ("MONGO_PORT",),
        "USER": ("MONGO_USER",),
        "PASSWORD": ("MONGO_PASSWORD",),
        "DATABASE": ("MONGO_DATABASE", "MONGODB_DATABASE", "MONGO_DB"),
    },
    "postgres": {
        # PG* es la convención de libpq: psql y psycopg conectan sin configurar nada.
        "URI": ("POSTGRES_URI", "POSTGRES_URL"),
        "HOST": ("POSTGRES_HOST", "PGHOST"),
        "PORT": ("POSTGRES_PORT", "PGPORT"),
        "USER": ("POSTGRES_USER", "PGUSER"),
        "PASSWORD": ("POSTGRES_PASSWORD", "PGPASSWORD"),
        "DATABASE": ("POSTGRES_DB", "PGDATABASE"),
    },
    "mysql": {
        "URI": ("MYSQL_URI", "MYSQL_URL"),
        "HOST": ("MYSQL_HOST",),
        "PORT": ("MYSQL_PORT",),
        "USER": ("MYSQL_USER",),
        "PASSWORD": ("MYSQL_PASSWORD",),
        "DATABASE": ("MYSQL_DATABASE",),
    },
    "redis": {
        "URI": ("REDIS_URL", "REDIS_URI"),
        "HOST": ("REDIS_HOST",),
        "PORT": ("REDIS_PORT",),
        "PASSWORD": ("REDIS_PASSWORD",),
    },
}

# Esquema de la URI → motor. Es lo que permite reconocer las bases ya vinculadas
# de una app existente sin depender de cómo se registró el vínculo.
_SCHEMES: Dict[str, str] = {
    "mongodb": "mongodb",
    "mongodb+srv": "mongodb",
    "postgresql": "postgres",
    "postgres": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "redis": "redis",
    "rediss": "redis",
}

# Variable universal, la que usan Django, Prisma, SQLAlchemy y compañía.
GENERIC_URL = "DATABASE_URL"

# Las bases de datos que guardan estado compiten por DATABASE_URL; un caché no.
_CACHE_ENGINES = ("redis",)

CANONICAL_NAMES = frozenset(
    name
    for engine in ENGINE_ALIASES.values()
    for names in engine.values()
    for name in names
) | {GENERIC_URL}

_URI_SUFFIXES = ("_URI", "_URL")


def engine_from_uri(uri: Any) -> Optional[str]:
    """Motor de una cadena de conexión ('mongodb://...' → 'mongodb'). None si no lo es."""
    text = str(uri or "").strip()
    scheme, sep, _ = text.partition("://")
    if not sep:
        return None
    return _SCHEMES.get(scheme.lower())


def engine_from_template(template_id: Any) -> Optional[str]:
    """Motor de un template del catálogo ('mongodb' → 'mongodb', 'postgres' → 'postgres').

    Misma normalización que AppDeployer._detect_db_template, para que el nombre
    del motor sea uno solo en todo el sistema.
    """
    candidate = str(template_id or "").strip().lower()
    for fragment, engine in (
        ("mongo", "mongodb"), ("postgres", "postgres"),
        ("mysql", "mysql"), ("mariadb", "mysql"), ("redis", "redis"),
    ):
        if fragment in candidate:
            return engine
    return None


def canonical_aliases(bindings: Iterable[Tuple[str, Mapping[str, Any]]]) -> Dict[str, str]:
    """Variables convencionales para las bases vinculadas a un ambiente.

    `bindings` son pares (motor, componentes), con los componentes ya resueltos
    (URI, HOST, PORT, USER, PASSWORD, DATABASE). Un motor con más de una base
    vinculada se omite: MONGO_URI no podría decir a cuál de las dos apunta.
    """
    by_engine: Dict[str, List[Mapping[str, Any]]] = {}
    for engine, components in bindings:
        if engine in ENGINE_ALIASES:
            by_engine.setdefault(engine, []).append(components)

    aliases: Dict[str, str] = {}
    for engine, items in by_engine.items():
        if len(items) != 1:
            continue
        components = items[0]
        for component, names in ENGINE_ALIASES[engine].items():
            value = str(components.get(component) or "")
            if not value:
                continue
            for name in names:
                aliases.setdefault(name, value)

    # DATABASE_URL apunta a "la" base de la app: solo existe si hay una sola.
    stores = [engine for engine in by_engine if engine not in _CACHE_ENGINES]
    if len(stores) == 1 and len(by_engine[stores[0]]) == 1:
        uri = str(by_engine[stores[0]][0].get("URI") or "")
        if uri:
            aliases.setdefault(GENERIC_URL, uri)
    return aliases


def bindings_from_literals(literals: Mapping[str, Any]) -> List[Tuple[str, Dict[str, str]]]:
    """Bases vinculadas deducidas de las variables ya inyectadas a una app.

    Sirve para apps creadas antes de que existieran los nombres convencionales:
    el vínculo vive en las propias variables ('<ALIAS>_URI' con su esquema).
    """
    found: List[Tuple[str, Dict[str, str]]] = []
    for key, value in literals.items():
        suffix = next((s for s in _URI_SUFFIXES if key.endswith(s)), None)
        if suffix is None or key in CANONICAL_NAMES:
            continue
        engine = engine_from_uri(value)
        if engine is None:
            continue
        prefix = key[: -len(suffix)]
        if not prefix:
            continue
        components = {
            k[len(prefix) + 1:]: str(v)
            for k, v in literals.items()
            if k.startswith(f"{prefix}_") and v is not None
        }
        components.setdefault("URI", str(value))
        found.append((engine, components))
    return found


def parse_kustomize_literals(content: str) -> Dict[str, str]:
    """Variables de un overlay: el primer bloque `literals:` del secretGenerator.

    Es el bloque que escribe AppDeployer._patch_overlay_secrets. El valor va tal
    cual hasta el fin de línea: una contraseña puede llevar '=' dentro.
    """
    literals: Dict[str, str] = {}
    in_literals = False
    done = False
    for line in content.split("\n"):
        stripped = line.strip()
        if not done and not in_literals and stripped.startswith("literals:"):
            in_literals = True
            continue
        if in_literals:
            if stripped.startswith("- ") and "=" in stripped:
                key, _, value = stripped[2:].partition("=")
                literals[key.strip()] = value
            elif stripped:
                in_literals = False
                done = True
    return literals


def missing_aliases(literals: Mapping[str, Any]) -> Dict[str, str]:
    """Nombres convencionales que le faltan a una app ya desplegada.

    Nunca pisa una variable existente: si la app ya define MONGO_URI (propia o
    de otro vínculo), se respeta lo que hay.
    """
    aliases = canonical_aliases(bindings_from_literals(literals))
    return {name: value for name, value in aliases.items() if name not in literals}
