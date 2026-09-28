"""Planes de cambios (app/services/change_plans.py).

Las mismas funciones validan el dry_run y la ejecución: si aquí algo pasa, en
producción también; si aquí se rechaza, el plan lo dice antes de tocar nada.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.services import change_plans as cp  # noqa: E402
from app.services import stack_launcher  # noqa: E402

FQDN = "ejemplo.com"


def app_doc(**overrides):
    doc = {
        "name": "tienda-api", "template": "fastapi-api", "category": "backend", "app_group": "tienda",
        "environments": ["dev", "prod"],
        "exposure": {"type": "public", "per_env": {"dev": "tailscale", "prod": "public"}},
        "is_root_domain": False,
    }
    doc.update(overrides)
    return doc


def current_domain(doc, fqdn=FQDN, domain_id="d1"):
    modes = {env: (doc["exposure"]["per_env"] or {}).get(env, doc["exposure"]["type"]) for env in doc["environments"]}
    public = {env: m for env, m in modes.items() if m in ("public", "both")}
    return {
        "id": domain_id, "fqdn": fqdn, "public": bool(public), "modes": modes,
        "urls": {env: f"https://{doc['name']}.{fqdn}" if env == "prod" else f"https://{env}-{doc['name']}.{fqdn}"
                 for env in public},
    }


class BusyTests(unittest.TestCase):
    def test_one_long_operation_at_a_time(self):
        self.assertIsNone(cp.busy_reason({"domain_move": {"state": "succeeded"}, "exposure_change": None}))
        reason = cp.busy_reason({"exposure_change": {"state": "running"}})
        self.assertIn("cambio de exposición", reason)


class AppPlanTests(unittest.TestCase):
    def test_the_plan_says_what_gets_created_and_where(self):
        plan = cp.app_plan(app_doc(), FQDN, creation_mode="scaffold", database_bindings={
            "prod": [{"app_name": "tienda-db", "env": "prod"}],
        })
        self.assertEqual(plan["urls"], {"prod": "https://tienda-api.ejemplo.com"})
        self.assertEqual(plan["exposure"], {"dev": "tailscale", "prod": "public"})
        self.assertEqual(plan["databases"], {"prod": ["tienda-db"]})
        self.assertTrue(any("repositorio 'tienda-api'" in step for step in plan["steps"]))

    def test_the_models_enums_count_as_their_value(self):
        """Un alta recién validada trae ExposureType.PUBLIC, no 'public': el plan no puede perder sus URLs."""
        import enum

        class Mode(str, enum.Enum):
            PUBLIC = "public"
            TAILSCALE = "tailscale"

        doc = app_doc(exposure={"type": Mode.PUBLIC, "per_env": {"dev": Mode.TAILSCALE, "prod": Mode.PUBLIC}})
        plan = cp.app_plan(doc, FQDN, creation_mode="scaffold")
        self.assertEqual(plan["urls"], {"prod": "https://tienda-api.ejemplo.com"})
        self.assertEqual(plan["exposure"], {"dev": "tailscale", "prod": "public"})

    def test_a_homepage_lives_on_the_bare_domain(self):
        plan = cp.app_plan(app_doc(name="tienda", is_root_domain=True), FQDN, creation_mode="scaffold")
        self.assertEqual(plan["urls"]["prod"], "https://ejemplo.com")
        self.assertTrue(plan["is_homepage"])

    def test_an_official_image_has_no_repository(self):
        doc = app_doc(name="tienda-db", exposure={"type": "internal", "per_env": {"prod": "internal"}},
                      environments=["prod"])
        plan = cp.app_plan(doc, FQDN, creation_mode="config-only")
        self.assertEqual(plan["urls"], {})
        self.assertIn("imagen oficial", plan["steps"][0])


class StackPlanTests(unittest.TestCase):
    STACK = {
        "id": "vue-fastapi-mongo", "name": "Vue + FastAPI + MongoDB",
        "components": [
            {"role": "database", "template": "mongodb", "suffix": "-db", "exposure": "internal"},
            {"role": "backend", "template": "fastapi-api", "suffix": "-api", "exposure": "public", "binds": "database"},
            {"role": "frontend", "template": "vue3-spa", "suffix": "", "exposure": "public",
             "consumes": "backend", "can_be_homepage": True},
        ],
    }

    def test_the_view_shows_names_urls_and_wiring(self):
        plan = stack_launcher.build_plan(stack=self.STACK, base_name="orbita", domain_fqdn=FQDN, domain_id="d1",
                                         environments=["prod"], homepage=True)
        view = cp.stack_plan_view(plan)
        by_role = {c["role"]: c for c in view["components"]}
        self.assertEqual(by_role["backend"]["connects_to"], "orbita-db")
        self.assertEqual(by_role["frontend"]["connects_to"], "orbita-api")
        self.assertEqual(by_role["frontend"]["url"], "https://ejemplo.com")
        self.assertIsNone(by_role["database"]["url"])
        self.assertTrue(view["homepage"])


class ExposurePlanTests(unittest.TestCase):
    def test_only_what_changes_is_in_the_plan(self):
        plan = cp.exposure_plan(app_doc(), FQDN, {"dev": "public", "prod": "public"})
        self.assertEqual(list(plan["changes"]), ["dev"])
        self.assertEqual(plan["changes"]["dev"]["url_after"], "https://dev-tienda-api.ejemplo.com")
        self.assertIsNone(plan["changes"]["dev"]["url_before"])
        self.assertTrue(any("abierta en internet" in w for w in plan["warnings"]))

    def test_turning_off_is_warned(self):
        plan = cp.exposure_plan(app_doc(), FQDN, {"prod": "off"})
        self.assertIn("se apaga", plan["warnings"][0])

    def test_nothing_to_change_is_a_conflict(self):
        with self.assertRaises(cp.ChangeError) as ctx:
            cp.exposure_plan(app_doc(), FQDN, {"prod": "public"})
        self.assertEqual(ctx.exception.status, 409)

    def test_unknown_environment_or_mode_is_a_bad_request(self):
        for per_env in ({"qa": "public"}, {"prod": "abierto"}, {}):
            with self.assertRaises(cp.ChangeError) as ctx:
                cp.exposure_plan(app_doc(), FQDN, per_env)
            self.assertEqual(ctx.exception.status, 400)

    def test_a_homepage_keeps_prod_public(self):
        with self.assertRaises(cp.ChangeError) as ctx:
            cp.exposure_plan(app_doc(is_root_domain=True), FQDN, {"prod": "tailscale"})
        self.assertEqual(ctx.exception.status, 422)

    def test_multi_port_apps_go_through_the_console(self):
        doc = app_doc(exposure={"type": "tailscale", "per_env": {"prod": "tailscale"},
                                "port_exposure": {"prod": {"mqtt": "tailscale"}}})
        with self.assertRaises(cp.ChangeError) as ctx:
            cp.exposure_plan(doc, FQDN, {"prod": "public"})
        self.assertEqual(ctx.exception.status, 422)


class DomainMovePlanTests(unittest.TestCase):
    def test_the_plan_shows_the_urls_before_and_after(self):
        doc = app_doc()
        plan = cp.domain_move_plan(doc, current_domain(doc), "nuevo.com", target_id="d2", collisions=[])
        self.assertEqual(plan["urls_before"], {"prod": "https://tienda-api.ejemplo.com"})
        self.assertEqual(plan["urls_after"], {"prod": "https://tienda-api.nuevo.com"})

    def test_rules_are_the_same_as_the_endpoint(self):
        doc = app_doc()
        private = app_doc(exposure={"type": "internal", "per_env": {"dev": "internal", "prod": "internal"}})
        cases = [
            (private, dict(target_id="d2", collisions=[]), 400),
            (doc, dict(target_id="d1", collisions=[]), 409),
            (doc, dict(target_id="d2", collisions=[{"app": "otra", "hosts": ["tienda-api.nuevo.com"]}]), 409),
            (doc, dict(target_id="d2", collisions=[], busy="Ya hay una mudanza"), 409),
        ]
        for app, kwargs, status in cases:
            with self.assertRaises(cp.ChangeError) as ctx:
                cp.domain_move_plan(app, current_domain(app), "nuevo.com", **kwargs)
            self.assertEqual(ctx.exception.status, status, kwargs)


class HomepagePlanTests(unittest.TestCase):
    def test_prod_moves_to_the_bare_domain(self):
        doc = app_doc(name="tienda")
        plan = cp.homepage_plan(doc, current_domain(doc), root_owner=None, collisions=[])
        self.assertEqual((plan["url_before"], plan["url_after"]), ("https://tienda.ejemplo.com", "https://ejemplo.com"))

    def test_rules_are_the_same_as_the_endpoint(self):
        doc = app_doc(name="tienda")
        private = app_doc(name="tienda", exposure={"type": "tailscale", "per_env": {"dev": "tailscale", "prod": "tailscale"}})
        cases = [
            (app_doc(name="tienda", is_root_domain=True), {}, 409),
            (private, {}, 422),
            (doc, {"root_owner": "otra-homepage"}, 409),
            (doc, {"collisions": [{"app": "otra", "hosts": ["ejemplo.com"]}]}, 409),
            (doc, {"busy": "Ya hay una conversión"}, 409),
        ]
        for app, kwargs, status in cases:
            args = {"root_owner": None, "collisions": [], **kwargs}
            with self.assertRaises(cp.ChangeError) as ctx:
                cp.homepage_plan(app, current_domain(app), **args)
            self.assertEqual(ctx.exception.status, status, kwargs)

    def test_without_a_domain_there_is_no_root(self):
        doc = app_doc(name="tienda")
        with self.assertRaises(cp.ChangeError) as ctx:
            cp.homepage_plan(doc, {**current_domain(doc), "fqdn": None}, root_owner=None, collisions=[])
        self.assertEqual(ctx.exception.status, 400)


class LinkPlanTests(unittest.TestCase):
    def test_the_plan_lists_names_never_values(self):
        plan = cp.link_plan("tienda-api", "tienda-db", kind="database", alias="TIENDA_DB", report={
            "prod": {"status": "agrega", "add": ["MONGO_URI", "TIENDA_DB_URI"], "keep": []},
        })
        self.assertEqual(plan["environments"]["prod"]["add"], ["MONGO_URI", "TIENDA_DB_URI"])
        self.assertNotIn("mongodb://", str(plan))

    def test_standard_names_that_stay_are_warned(self):
        plan = cp.link_plan("tienda-api", "segunda-db", kind="database", alias="SEGUNDA_DB", report={
            "prod": {"status": "agrega", "add": ["SEGUNDA_DB_URI"], "keep": ["MONGO_URI"]},
        })
        self.assertIn("MONGO_URI", plan["warnings"][0])

    def test_nothing_to_add_is_a_conflict(self):
        with self.assertRaises(cp.ChangeError) as ctx:
            cp.link_plan("tienda-api", "tienda-db", kind="database", alias="TIENDA_DB", report={
                "prod": {"status": "al_dia", "add": [], "keep": ["TIENDA_DB_URI"]},
            })
        self.assertEqual(ctx.exception.status, 409)

    def test_unlink_lists_what_goes_away(self):
        plan = cp.unlink_plan("tienda-api", "pagos-api", {"prod": ["PAGOS_API_URL", "PAGOS_API_HOST"]})
        self.assertEqual(plan["remove"], {"prod": ["PAGOS_API_HOST", "PAGOS_API_URL"]})


if __name__ == "__main__":
    unittest.main()
