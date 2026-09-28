"""Alta de una app en pocas palabras (app/services/app_blueprint.py).

Lo que importa: el cuerpo de POST /apps tiene que ser el mismo que armaría el
Wizard con esas respuestas, para que crear desde un agente no sea un camino
distinto con reglas propias.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import app_blueprint as bp  # noqa: E402

FASTAPI = {"id": "fastapi-api", "category": "backend", "status": "ready", "port": 8000,
           "creation_modes": ["scaffold", "empty", "upload"]}
VUE = {"id": "vue3-spa", "category": "frontend", "status": "ready", "port": 80,
       "creation_modes": ["scaffold", "empty", "upload"]}
MONGO = {"id": "mongodb", "category": "database", "status": "ready", "port": 27017,
         "creation_modes": ["config-only"]}
EMQX = {"id": "emqx", "category": "iot", "status": "ready", "port": 18083, "creation_modes": ["config-only"],
        "exposure": {"mode": "tailscale"}, "ports": [{"name": "dashboard"}, {"name": "mqtt"}]}
N8N = {"id": "n8n", "category": "workflow", "status": "ready", "port": 5678, "creation_modes": ["config-only"],
       "exposure": {"mode": "public"}}

TIENDA_DB = {"name": "tienda-db", "template": "mongodb", "environments": ["dev", "prod"]}
TIENDA_API = {"name": "tienda-api", "template": "fastapi-api", "environments": ["prod"],
              "domain": {"urls": {"prod": "https://tienda-api.ejemplo.com"}}}


class WizardDefaultsTests(unittest.TestCase):
    def test_a_web_app_is_public_in_prod_and_on_the_vpn_elsewhere(self):
        payload = bp.build(FASTAPI, name="tienda-api", environments=["dev"])
        self.assertEqual(payload["environments"], ["dev", "prod"])
        self.assertEqual(payload["exposure"]["per_env"], {"dev": "tailscale", "prod": "public"})
        self.assertEqual(payload["creation_mode"], "scaffold")
        self.assertEqual(payload["specs"]["port"], 8000)

    def test_prod_is_always_there_and_in_order(self):
        self.assertEqual(bp.build(FASTAPI, name="x-api", environments=["prod", "dev", "staging"])["environments"],
                         ["dev", "staging", "prod"])
        self.assertEqual(bp.build(FASTAPI, name="x-api")["environments"], ["prod"])

    def test_a_database_is_an_official_image_and_stays_internal(self):
        payload = bp.build(MONGO, name="tienda-db")
        self.assertEqual(payload["creation_mode"], "config-only")
        self.assertEqual(payload["exposure"]["per_env"], {"prod": "internal"})

    def test_the_catalog_mode_wins_over_the_category_default(self):
        self.assertEqual(bp.build(N8N, name="flujos")["exposure"]["type"], "public")

    def test_an_explicit_exposure_applies_everywhere(self):
        payload = bp.build(FASTAPI, name="interna", environments=["dev"], exposure="internal")
        self.assertEqual(payload["exposure"]["per_env"], {"dev": "internal", "prod": "internal"})

    def test_a_homepage_forces_prod_public_and_asks_for_the_root(self):
        payload = bp.build(VUE, name="tienda", exposure="tailscale", homepage=True)
        self.assertEqual(payload["exposure"]["per_env"]["prod"], "public")
        self.assertTrue(payload["template_config"]["use_root_domain"])


class ConnectionTests(unittest.TestCase):
    def test_an_api_with_a_database_is_bound_like_the_wizard_does(self):
        payload = bp.build(FASTAPI, name="tienda-api", environments=["dev"], database=TIENDA_DB)
        self.assertEqual(payload["database_bindings"]["dev"], [
            {"app_name": "tienda-db", "env": "dev", "template": "mongodb", "alias": "TIENDA_DB"},
        ])
        self.assertEqual(payload["database_bindings"]["prod"][0]["env"], "prod")
        # La plantilla de API elige su docker-compose local según el motor.
        self.assertEqual(payload["template_config"]["DB_ENGINE"], "mongodb")

    def test_each_environment_needs_the_same_environment_in_the_database(self):
        with self.assertRaises(bp.BlueprintError) as ctx:
            bp.build(FASTAPI, name="x-api", environments=["staging"], database=TIENDA_DB)
        self.assertIn("staging", str(ctx.exception))

    def test_a_frontend_never_gets_database_credentials(self):
        with self.assertRaises(bp.BlueprintError):
            bp.build(VUE, name="tienda", database=TIENDA_DB)

    def test_only_databases_can_be_bound_as_databases(self):
        with self.assertRaises(bp.BlueprintError):
            bp.build(FASTAPI, name="x-api", database=TIENDA_API)

    def test_a_frontend_points_to_the_public_url_of_its_api(self):
        payload = bp.build(VUE, name="tienda", api=TIENDA_API)
        self.assertEqual(payload["template_config"]["API_URL"], "https://tienda-api.ejemplo.com")

    def test_a_private_api_is_useless_to_a_browser(self):
        private = {**TIENDA_API, "domain": {"urls": {}}}
        with self.assertRaises(bp.BlueprintError) as ctx:
            bp.build(VUE, name="tienda", api=private)
        self.assertIn("no es pública", str(ctx.exception))

    def test_api_is_only_for_frontends(self):
        with self.assertRaises(bp.BlueprintError):
            bp.build(FASTAPI, name="otra-api", api=TIENDA_API)


class RefusalTests(unittest.TestCase):
    def test_multi_port_templates_go_through_the_wizard(self):
        with self.assertRaises(bp.BlueprintError) as ctx:
            bp.build(EMQX, name="broker")
        self.assertIn("Wizard", str(ctx.exception))

    def test_templates_that_are_not_ready_are_refused(self):
        with self.assertRaises(bp.BlueprintError):
            bp.build({**FASTAPI, "status": "coming_soon"}, name="x-api")

    def test_unknown_environments_and_exposures_are_refused(self):
        with self.assertRaises(bp.BlueprintError):
            bp.build(FASTAPI, name="x-api", environments=["qa"])
        with self.assertRaises(bp.BlueprintError):
            bp.build(FASTAPI, name="x-api", exposure="both")


if __name__ == "__main__":
    unittest.main()
