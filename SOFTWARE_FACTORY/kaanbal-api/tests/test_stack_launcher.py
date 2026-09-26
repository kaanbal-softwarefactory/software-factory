"""Plan de un stack (app/services/stack_launcher.py).

Lo que se arma a mano una y otra vez: base + API vinculada + frontend que le
pega. El plan decide nombres, orden, exposición y cableado antes de crear nada.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# domain_service toca Mongo al importarse; el plan solo usa sus funciones puras.
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.services import stack_launcher as sl  # noqa: E402


STACK = {
    "id": "vue-fastapi-mongo",
    "name": "Vue + FastAPI + MongoDB",
    "components": [
        # A propósito en desorden: el plan debe ordenarlos.
        {"role": "frontend", "template": "vue3-spa", "suffix": "", "exposure": "public",
         "consumes": "backend", "can_be_homepage": True},
        {"role": "database", "template": "mongodb", "suffix": "-db", "exposure": "internal"},
        {"role": "backend", "template": "fastapi-api", "suffix": "-api", "exposure": "public",
         "binds": "database"},
    ],
}


def plan(**overrides):
    kwargs = dict(
        stack=STACK, base_name="orbit", domain_fqdn="north-star-bay.store",
        domain_id="d2", environments=["prod"],
    )
    kwargs.update(overrides)
    return sl.build_plan(**kwargs)


class OrderTests(unittest.TestCase):
    def test_database_first_then_api_then_frontend(self):
        """La API necesita las credenciales de la base; el frontend, la URL de la API."""
        self.assertEqual([c["role"] for c in plan()["components"]], ["database", "backend", "frontend"])

    def test_names_derive_from_the_base_name(self):
        self.assertEqual(
            [c["name"] for c in plan()["components"]],
            ["orbit-db", "orbit-api", "orbit"],
        )

    def test_without_a_name_the_stack_takes_the_domain(self):
        self.assertEqual(plan(base_name="")["base"], "north-star-bay")

    def test_everything_lands_in_one_group(self):
        groups = {c["app_group"] for c in plan()["components"]}
        self.assertEqual(groups, {"orbit"})


class WiringTests(unittest.TestCase):
    def test_api_is_bound_to_the_stack_database(self):
        api = next(c for c in plan()["components"] if c["role"] == "backend")
        binding = api["database_bindings"]["prod"][0]
        self.assertEqual(binding["app_name"], "orbit-db")
        self.assertEqual(binding["alias"], "ORBIT_DB")
        self.assertEqual(api["template_config"]["DB_ENGINE"], "mongodb")

    def test_binding_covers_every_environment(self):
        api = next(c for c in plan(environments=["dev", "prod"])["components"] if c["role"] == "backend")
        self.assertEqual(sorted(api["database_bindings"]), ["dev", "prod"])

    def test_frontend_receives_the_public_url_of_its_api(self):
        front = next(c for c in plan()["components"] if c["role"] == "frontend")
        self.assertEqual(front["template_config"]["API_URL"], "https://orbit-api.north-star-bay.store")

    def test_a_private_api_is_reached_inside_the_cluster(self):
        private = {**STACK, "components": [
            {"role": "database", "template": "mongodb", "suffix": "-db", "exposure": "internal"},
            {"role": "backend", "template": "fastapi-api", "suffix": "-api", "exposure": "internal", "binds": "database"},
            {"role": "frontend", "template": "vue3-spa", "suffix": "", "exposure": "public", "consumes": "backend"},
        ]}
        front = next(c for c in plan(stack=private)["components"] if c["role"] == "frontend")
        self.assertEqual(front["template_config"]["API_URL"], "http://orbit-api.prod.svc.cluster.local")


class HomepageTests(unittest.TestCase):
    """El stack que abre un dominio: el frontend ocupa la raíz."""

    def test_frontend_takes_the_root_of_the_domain(self):
        front = next(c for c in plan(homepage=True)["components"] if c["role"] == "frontend")
        self.assertTrue(front["is_root_domain"])
        self.assertEqual(front["public_host"], "north-star-bay.store")
        self.assertTrue(front["template_config"]["use_root_domain"])

    def test_without_homepage_the_frontend_is_a_subdomain(self):
        front = next(c for c in plan()["components"] if c["role"] == "frontend")
        self.assertFalse(front["is_root_domain"])
        self.assertEqual(front["public_host"], "orbit.north-star-bay.store")

    def test_the_database_never_takes_the_root(self):
        roots = [c["name"] for c in plan(homepage=True)["components"] if c["is_root_domain"]]
        self.assertEqual(roots, ["orbit"])


class ExposureTests(unittest.TestCase):
    def test_the_database_stays_inside_the_cluster(self):
        db = next(c for c in plan()["components"] if c["role"] == "database")
        self.assertEqual(db["exposure"]["per_env"], {"prod": "internal"})
        self.assertIsNone(db["public_host"])

    def test_prod_is_always_part_of_the_stack(self):
        """Un stack sin prod no tendría dónde vivir el sitio."""
        self.assertIn("prod", plan(environments=["dev"])["environments"])

    def test_databases_are_official_images(self):
        db = next(c for c in plan()["components"] if c["role"] == "database")
        self.assertEqual(db["creation_mode"], "config-only")
        self.assertEqual(
            [c["creation_mode"] for c in plan()["components"] if c["role"] != "database"],
            ["scaffold", "scaffold"],
        )


class CollisionTests(unittest.TestCase):
    def test_a_taken_name_stops_the_stack_before_creating_anything(self):
        with self.assertRaises(sl.StackPlanError) as ctx:
            plan(taken_names=["orbit-api"])
        self.assertIn("orbit-api", str(ctx.exception))

    def test_a_stack_without_components_is_rejected(self):
        with self.assertRaises(sl.StackPlanError):
            plan(stack={"id": "vacio", "components": []})

    def test_a_component_wired_to_something_missing_is_rejected(self):
        broken = {"id": "roto", "components": [
            {"role": "backend", "template": "fastapi-api", "suffix": "-api", "binds": "database"},
        ]}
        with self.assertRaises(sl.StackPlanError):
            plan(stack=broken)


class PayloadTests(unittest.TestCase):
    """Cada pieza se crea con el mismo cuerpo que manda el Wizard."""

    def test_payload_carries_group_domain_and_bindings(self):
        api = next(c for c in plan()["components"] if c["role"] == "backend")
        payload = sl.app_create_payload(api, description="stack")
        self.assertEqual(payload["name"], "orbit-api")
        self.assertEqual(payload["template"], "fastapi-api")
        self.assertEqual(payload["category"], "backend")
        self.assertEqual(payload["app_group"], "orbit")
        self.assertEqual(payload["domain_id"], "d2")
        self.assertIn("prod", payload["database_bindings"])

    def test_a_database_payload_has_no_bindings(self):
        db = next(c for c in plan()["components"] if c["role"] == "database")
        self.assertNotIn("database_bindings", sl.app_create_payload(db))

    def test_public_urls_are_reported_per_role(self):
        urls = sl.public_urls(plan(homepage=True))
        self.assertEqual(urls["frontend"], "https://north-star-bay.store")
        self.assertEqual(urls["backend"], "https://orbit-api.north-star-bay.store")
        self.assertNotIn("database", urls)


if __name__ == "__main__":
    unittest.main()
