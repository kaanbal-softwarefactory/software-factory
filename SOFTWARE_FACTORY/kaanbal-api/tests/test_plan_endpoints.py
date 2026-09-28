"""dry_run y plan_id en los endpoints reales, con una base Mongo falsa en memoria.

Lo que se prueba es el cableado: que un dry_run no cree ni mueva nada, que un
plan viejo se rechace sin tocar nada, que el plan mostrado sí se aplique, y que
la consola (sin dry_run ni plan_id) siga igual que siempre. Las reglas de cada
plan tienen sus propias pruebas en test_change_plans.py.

Necesita las dependencias completas de la API (bson, jose, passlib): corre en el
CI y en su réplica; sin ellas, se salta.
"""

import copy
import os
import re
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

try:
    from bson import ObjectId
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.models import User
    from app.routers import apps as apps_router
    from app.routers import stacks as stacks_router
    from app.routers.auth import get_current_active_user
    from app.services import domain_service
    from app.services.activity_log import ActivityLogService
except ImportError as exc:  # pragma: no cover - depende del entorno
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

_MISSING = object()


def _get(doc, dotted):
    value = doc
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _set(doc, dotted, value):
    parts = dotted.split(".")
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value


def _matches(doc, query):
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = _get(doc, key)
        if isinstance(cond, dict) and any(str(op).startswith("$") for op in cond):
            for op, arg in cond.items():
                if op == "$regex":
                    flags = re.I if "i" in cond.get("$options", "") else 0
                    if not (isinstance(value, str) and re.search(arg, value, flags)):
                        return False
                elif op == "$options":
                    continue
                elif op == "$ne":
                    if value is not _MISSING and value == arg:
                        return False
                elif op == "$in":
                    if value is _MISSING or value not in arg:
                        return False
                elif op == "$exists":
                    if (value is not _MISSING) != bool(arg):
                        return False
                else:
                    raise NotImplementedError(op)
        elif value is _MISSING or value != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        self.docs.sort(key=lambda d: str(_get(d, key)), reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        return [copy.deepcopy(doc) for doc in (self.docs if length is None else self.docs[:length])]


class FakeCollection:
    def __init__(self):
        self.docs = []

    def find(self, query=None, projection=None):
        return FakeCursor([doc for doc in self.docs if _matches(doc, query)])

    async def find_one(self, query=None, projection=None):
        for doc in self.docs:
            if _matches(doc, query):
                return copy.deepcopy(doc)
        return None

    async def insert_one(self, doc):
        stored = copy.deepcopy(doc)
        stored.setdefault("_id", ObjectId())
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if _matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    _set(doc, key, copy.deepcopy(value))
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def delete_many(self, query):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, query)]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    async def count_documents(self, query):
        return len([doc for doc in self.docs if _matches(doc, query)])


class FakeDb:
    def __init__(self):
        object.__setattr__(self, "_collections", {})

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._collections.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)


STACK = {
    "id": "vue-fastapi-mongo", "name": "Vue + FastAPI + MongoDB",
    "components": [
        {"role": "database", "template": "mongodb", "suffix": "-db", "exposure": "internal"},
        {"role": "backend", "template": "fastapi-api", "suffix": "-api", "exposure": "public", "binds": "database"},
        {"role": "frontend", "template": "vue3-spa", "suffix": "", "exposure": "public",
         "consumes": "backend", "can_be_homepage": True},
    ],
}


class FakeDeployer:
    """Calcula el reporte de un vínculo y llama before_push, como el de verdad; nunca empuja nada."""

    pushed = []

    async def link_apps(self, consumer, provider, *, environments, alias, kind, ports=None, dry_run=False, before_push=None):
        report = {env: {"status": "agrega", "add": [f"{alias}_HOST", f"{alias}_URL"], "keep": []} for env in environments}
        if before_push is not None:
            before_push(report)
        if not dry_run:
            FakeDeployer.pushed.append(("link", consumer["name"], provider["name"]))
        return {"environments": report, "committed": not dry_run}

    async def unlink_apps(self, app_name, names_by_env, *, provider_name):
        FakeDeployer.pushed.append(("unlink", app_name, provider_name))
        return {"environments": {env: {"status": "quitadas", "removed": names} for env, names in names_by_env.items()},
                "committed": True}


async def _noop(*args, **kwargs):
    return None


@unittest.skipIf(IMPORT_ERROR is not None, f"faltan dependencias de la API: {IMPORT_ERROR}")
class PlanEndpointTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self.default_id = ObjectId()
        self.other_id = ObjectId()
        self.db.domains.docs.extend([
            {"_id": self.default_id, "fqdn": "ejemplo.com", "is_default": True},
            {"_id": self.other_id, "fqdn": "nuevo.com", "is_default": False},
        ])
        domain = str(self.default_id)
        self.db.apps.docs.extend([
            {"_id": ObjectId(), "name": "tienda-api", "template": "fastapi-api", "category": "backend",
             "domain_id": domain, "environments": ["dev", "prod"], "status": "running",
             "exposure": {"type": "public", "per_env": {"dev": "tailscale", "prod": "public"}}},
            {"_id": ObjectId(), "name": "tienda", "template": "vue3-spa", "category": "frontend",
             "domain_id": domain, "environments": ["prod"], "status": "running",
             "exposure": {"type": "public", "per_env": {"prod": "public"}}},
            {"_id": ObjectId(), "name": "pagos-api", "template": "fastapi-api", "category": "backend",
             "domain_id": domain, "environments": ["dev", "prod"], "status": "running",
             "exposure": {"type": "internal", "per_env": {"dev": "internal", "prod": "internal"}}},
        ])
        FakeDeployer.pushed = []

        patches = [
            mock.patch.object(apps_router, "get_db", lambda: self.db),
            mock.patch.object(stacks_router, "get_db", lambda: self.db),
            mock.patch.object(domain_service, "get_db", lambda: self.db),
            # A nivel de clase: si un router importara el módulo en vez de la instancia, esto no lo taparía.
            mock.patch.object(ActivityLogService, "log", _noop),
            mock.patch.object(ActivityLogService, "error", _noop),
            mock.patch.object(apps_router, "start_deploy", lambda *a, **k: "/stream"),
            mock.patch.object(apps_router, "_promote_to_root_in_background", _noop),
            mock.patch.object(apps_router, "_move_domain_in_background", _noop),
            mock.patch.object(apps_router, "_change_exposure_in_background", _noop),
            mock.patch.object(apps_router, "_service_port", mock.AsyncMock(return_value=8000)),
            mock.patch.object(apps_router, "AppDeployer", FakeDeployer),
            mock.patch.object(stacks_router, "_run_stack", _noop),
            mock.patch.object(stacks_router.template_service, "get_stack_details", mock.AsyncMock(return_value=STACK)),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        app = FastAPI()
        app.include_router(apps_router.router, prefix="/api/v1/apps")
        app.include_router(stacks_router.router, prefix="/api/v1/stacks")
        app.dependency_overrides[get_current_active_user] = lambda: User(username="ana")
        self.client = TestClient(app)

    def app_doc(self, name):
        return next(doc for doc in self.db.apps.docs if doc["name"] == name)

    # ── Alta ──────────────────────────────────────────────────────────────
    NEW_APP = {"name": "nueva-api", "template": "fastapi-api", "category": "backend", "environments": ["prod"],
               "exposure": {"type": "public", "per_env": {"prod": "public"}}}

    def test_a_dry_run_creates_nothing(self):
        response = self.client.post("/api/v1/apps?dry_run=true", json=self.NEW_APP)
        self.assertEqual(response.status_code, 200, response.text)
        answer = response.json()
        self.assertEqual(answer["plan"]["urls"], {"prod": "https://nueva-api.ejemplo.com"})
        self.assertRegex(answer["plan_id"], r"^[0-9a-f]{16}$")
        self.assertEqual(len(self.db.apps.docs), 3)

    def test_a_stale_plan_creates_nothing(self):
        response = self.client.post("/api/v1/apps?plan_id=0000000000000000", json=self.NEW_APP)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.db.apps.docs), 3)

    def test_the_shown_plan_is_the_one_applied(self):
        plan_id = self.client.post("/api/v1/apps?dry_run=true", json=self.NEW_APP).json()["plan_id"]
        response = self.client.post(f"/api/v1/apps?plan_id={plan_id}", json=self.NEW_APP)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.app_doc("nueva-api")["status"], "deploying")

    def test_the_console_path_is_unchanged(self):
        response = self.client.post("/api/v1/apps", json=self.NEW_APP)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(len(self.db.apps.docs), 4)

    def test_a_taken_name_is_reported_by_the_plan(self):
        response = self.client.post("/api/v1/apps?dry_run=true", json={**self.NEW_APP, "name": "tienda-api"})
        self.assertEqual(response.status_code, 409)

    # ── Homepage, dominio y exposición ───────────────────────────────────
    def test_homepage_plan_then_apply(self):
        answer = self.client.post("/api/v1/apps/tienda/homepage?dry_run=true").json()
        self.assertEqual(answer["plan"]["url_after"], "https://ejemplo.com")
        self.assertNotIn("root_promotion", self.app_doc("tienda"))
        response = self.client.post(f"/api/v1/apps/tienda/homepage?plan_id={answer['plan_id']}")
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.app_doc("tienda")["root_promotion"]["state"], "running")

    def test_one_root_per_domain(self):
        self.app_doc("tienda")["is_root_domain"] = True
        response = self.client.post("/api/v1/apps/tienda-api/homepage?dry_run=true")
        self.assertEqual(response.status_code, 409)
        self.assertIn("tienda", response.json()["detail"])

    def test_domain_move_plan_then_apply(self):
        body = {"domain_id": str(self.other_id)}
        answer = self.client.post("/api/v1/apps/tienda-api/domain?dry_run=true", json=body).json()
        self.assertEqual(answer["plan"]["urls_after"], {"prod": "https://tienda-api.nuevo.com"})
        response = self.client.post(f"/api/v1/apps/tienda-api/domain?plan_id={answer['plan_id']}", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.app_doc("tienda-api")["domain_move"]["to"], "nuevo.com")

    def test_exposure_runs_in_the_background_one_change_at_a_time(self):
        body = {"per_env": {"dev": "public"}}
        answer = self.client.post("/api/v1/apps/tienda-api/exposure?dry_run=true", json=body).json()
        self.assertEqual(answer["plan"]["changes"]["dev"]["url_after"], "https://dev-tienda-api.ejemplo.com")
        response = self.client.post(f"/api/v1/apps/tienda-api/exposure?plan_id={answer['plan_id']}", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.app_doc("tienda-api")["exposure_change"]["per_env"], {"dev": "public"})
        busy = self.client.post("/api/v1/apps/tienda-api/domain?dry_run=true", json={"domain_id": str(self.other_id)})
        self.assertEqual(busy.status_code, 409)
        self.assertIn("en curso", busy.json()["detail"])

    def test_get_app_shows_long_operations(self):
        self.app_doc("tienda-api")["exposure_change"] = {"state": "succeeded", "per_env": {"dev": "public"}}
        detail = self.client.get("/api/v1/apps/tienda-api").json()
        self.assertEqual(detail["exposure_change"]["state"], "succeeded")
        self.assertIn("domain_move", detail)

    # ── Vínculos ─────────────────────────────────────────────────────────
    def test_link_plan_apply_and_unlink(self):
        body = {"to_app": "pagos-api"}
        answer = self.client.post("/api/v1/apps/tienda-api/links?dry_run=true", json=body).json()
        self.assertEqual(answer["plan"]["environments"]["prod"]["add"], ["PAGOS_API_HOST", "PAGOS_API_URL"])
        self.assertEqual(FakeDeployer.pushed, [])
        self.assertEqual(self.db.service_links.docs, [])

        stale = self.client.post("/api/v1/apps/tienda-api/links?plan_id=0000000000000000", json=body)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(FakeDeployer.pushed, [])

        applied = self.client.post(f"/api/v1/apps/tienda-api/links?plan_id={answer['plan_id']}", json=body)
        self.assertEqual(applied.status_code, 201, applied.text)
        links = self.db.service_links.docs
        self.assertEqual(sorted(link["from_env"] for link in links), ["dev", "prod"])
        self.assertEqual(links[0]["published_names"], ["PAGOS_API_HOST", "PAGOS_API_URL"])

        unplan = self.client.delete("/api/v1/apps/tienda-api/links/pagos-api?dry_run=true").json()
        self.assertEqual(unplan["plan"]["remove"]["prod"], ["PAGOS_API_HOST", "PAGOS_API_URL"])
        removed = self.client.delete(f"/api/v1/apps/tienda-api/links/pagos-api?plan_id={unplan['plan_id']}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(self.db.service_links.docs, [])

    def test_a_database_cannot_be_the_consumer(self):
        self.db.apps.docs.append({"_id": ObjectId(), "name": "tienda-db", "template": "mongodb", "category": "database",
                                  "environments": ["prod"], "exposure": {"type": "internal"}})
        response = self.client.post("/api/v1/apps/tienda-db/links?dry_run=true", json={"to_app": "tienda-api"})
        self.assertEqual(response.status_code, 400)

    # ── Stacks ───────────────────────────────────────────────────────────
    STACK_BODY = {"stack_id": "vue-fastapi-mongo", "name": "orbita", "environments": ["prod"], "homepage": False}

    def test_stack_plan_then_launch(self):
        answer = self.client.post("/api/v1/stacks?dry_run=true", json=self.STACK_BODY).json()
        self.assertEqual([c["name"] for c in answer["plan"]["components"]], ["orbita-db", "orbita-api", "orbita"])
        self.assertEqual(self.db.stack_runs.docs, [])
        response = self.client.post(f"/api/v1/stacks?plan_id={answer['plan_id']}", json=self.STACK_BODY)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.db.stack_runs.docs[0]["state"], "running")

    def test_a_running_stack_is_a_notice_in_the_plan_and_a_conflict_when_applying(self):
        from datetime import datetime

        self.db.stack_runs.docs.append({"_id": ObjectId(), "state": "running", "base": "otro",
                                        "started_at": datetime.utcnow()})
        answer = self.client.post("/api/v1/stacks?dry_run=true", json=self.STACK_BODY).json()
        self.assertIn("otro", answer["notices"][0])
        response = self.client.post(f"/api/v1/stacks?plan_id={answer['plan_id']}", json=self.STACK_BODY)
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
