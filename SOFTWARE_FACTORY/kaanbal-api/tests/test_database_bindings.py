"""Vincular una app a su base: el camino real del deployer, sin clúster ni Vault.

Hasta la 1.2.0 toda alta con una base vinculada moría en "Resolving database
bindings" con `'str' object has no attribute 'canonical_aliases'`: una variable
local llamada db_env tapaba al módulo db_env. Nada lo ejecutaba en las pruebas;
estas lo ejecutan de punta a punta (credenciales → URI → nombres estándar).

Necesita las dependencias completas de la API (bson, pydantic-settings): corre en
el CI y en su réplica; sin ellas, se salta.
"""

import asyncio
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

try:
    from app.services import app_deployer
    from app.services import app_links
except ImportError as exc:  # pragma: no cover - depende del entorno
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeApps:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None):
        wanted = set((query.get("name") or {}).get("$in") or [])
        return FakeCursor(doc for doc in self.docs if doc["name"] in wanted)


DATABASES = [
    {"name": "residuos-bd", "template": "postgres", "category": "database"},
    {"name": "tienda-db", "template": "mongodb", "category": "database"},
]
SECRETS = {
    ("residuos-bd", "prod"): {"POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": "clave-de-prueba", "POSTGRES_DB": "residuos"},
    ("tienda-db", "prod"): {"MONGO_INITDB_ROOT_USERNAME": "admin", "MONGO_INITDB_ROOT_PASSWORD": "otra-clave"},
}


@unittest.skipIf(IMPORT_ERROR is not None, f"faltan dependencias de la API: {IMPORT_ERROR}")
class ResolveBindingsTests(unittest.TestCase):
    def setUp(self):
        # Sin __init__: no hace falta credenciales ni proveedor de Git para resolver vínculos.
        self.deployer = app_deployer.AppDeployer.__new__(app_deployer.AppDeployer)

        async def read_secrets(app_name, env):
            return dict(SECRETS.get((app_name, env), {}))

        self.deployer._read_app_secrets = read_secrets
        db = SimpleNamespace(apps=FakeApps(DATABASES))
        patcher = mock.patch.object(app_deployer, "get_db", lambda: db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def resolve(self, consumer_template, bindings):
        app_data = SimpleNamespace(template=consumer_template, database_bindings=bindings)
        return asyncio.run(self.deployer._resolve_database_bindings("residuos-api", app_data, ["prod"]))

    def test_an_api_bound_to_postgres_gets_prefixed_and_standard_names(self):
        """El caso de residuos-api: FastAPI + PostgreSQL."""
        result = self.resolve("fastapi-api", {"prod": [
            {"app_name": "residuos-bd", "env": "prod", "template": "postgres", "alias": "RESIDUOS_BD"},
        ]})
        variables = result["prod"]
        self.assertEqual(variables["RESIDUOS_BD_HOST"], "residuos-bd.prod.svc.cluster.local")
        self.assertTrue(variables["RESIDUOS_BD_URI"].startswith("postgresql://postgres:"))
        # Los nombres estándar, los que usa el código de la plantilla.
        self.assertEqual(variables["DATABASE_URL"], variables["RESIDUOS_BD_URI"])
        self.assertEqual(variables["PGHOST"], "residuos-bd.prod.svc.cluster.local")
        self.assertEqual(variables["PGDATABASE"], "residuos")

    def test_a_mongo_binding_publishes_mongo_uri(self):
        result = self.resolve("fastapi-api", {"prod": [
            {"app_name": "tienda-db", "env": "prod", "template": "mongodb", "alias": "TIENDA_DB"},
        ]})
        self.assertEqual(result["prod"]["MONGO_URI"], result["prod"]["TIENDA_DB_URI"])

    def test_two_databases_of_the_same_engine_skip_the_ambiguous_short_names(self):
        result = self.resolve("fastapi-api", {"prod": [
            {"app_name": "residuos-bd", "env": "prod", "template": "postgres", "alias": "UNA"},
            {"app_name": "residuos-bd", "env": "prod", "template": "postgres", "alias": "OTRA"},
        ]})
        self.assertIn("UNA_URI", result["prod"])
        self.assertIn("OTRA_URI", result["prod"])
        self.assertNotIn("DATABASE_URL", result["prod"])

    def test_link_apps_resolves_a_database_through_the_same_path(self):
        variables = asyncio.run(self.deployer._link_variables(
            {"name": "residuos-api", "template": "fastapi-api"}, DATABASES[0], "prod", "RESIDUOS_BD", "database", 0,
        ))
        self.assertIn("DATABASE_URL", variables)
        self.assertIn("RESIDUOS_BD_PASSWORD", variables)

    def test_link_apps_stops_when_the_credentials_are_missing(self):
        with self.assertRaises(app_links.LinkError):
            asyncio.run(self.deployer._link_variables(
                {"name": "residuos-api", "template": "fastapi-api"}, DATABASES[0], "dev", "RESIDUOS_BD", "database", 0,
            ))


if __name__ == "__main__":
    unittest.main()
