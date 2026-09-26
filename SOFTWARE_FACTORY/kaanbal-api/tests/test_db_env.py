"""Nombres de las variables de una base vinculada (app/services/db_env.py).

Caso real: el backend de north-star-bay quedó en CrashLoopBackOff con
KeyError: 'MONGO_URI'. El vínculo estaba bien hecho, pero Kaanbal solo publicaba
NORTH_STAR_BAY_BD_URI —el nombre depende de cómo se llame la base en esta
instalación y el autor de la app no puede adivinarlo.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import db_env  # noqa: E402


MONGO_URI = "mongodb://admin:s3cr3t@north-star-bay-bd.prod.svc.cluster.local:27017/north_star_bay_api?authSource=admin"
PG_URI = "postgresql://postgres:pw@clientes-db.prod.svc.cluster.local:5432/clientes"

ORBIT_LITERALS = {
    "APP_SECRET": "xxx",
    "NORTH_STAR_BAY_BD_URI": MONGO_URI,
    "NORTH_STAR_BAY_BD_HOST": "north-star-bay-bd.prod.svc.cluster.local",
    "NORTH_STAR_BAY_BD_PORT": "27017",
    "NORTH_STAR_BAY_BD_USER": "admin",
    "NORTH_STAR_BAY_BD_PASSWORD": "s3cr3t",
    "NORTH_STAR_BAY_BD_DATABASE": "north_star_bay_api",
}


class CanonicalAliasTests(unittest.TestCase):
    def test_mongo_binding_publishes_the_conventional_names(self):
        aliases = db_env.canonical_aliases([("mongodb", {"URI": MONGO_URI, "HOST": "h", "PORT": "27017"})])
        self.assertEqual(aliases["MONGO_URI"], MONGO_URI)
        self.assertEqual(aliases["MONGODB_URI"], MONGO_URI)
        self.assertEqual(aliases["DATABASE_URL"], MONGO_URI)
        self.assertEqual(aliases["MONGO_HOST"], "h")

    def test_postgres_binding_speaks_libpq(self):
        aliases = db_env.canonical_aliases([
            ("postgres", {"URI": PG_URI, "HOST": "h", "PORT": "5432", "USER": "postgres", "PASSWORD": "pw", "DATABASE": "clientes"}),
        ])
        self.assertEqual(aliases["PGHOST"], "h")
        self.assertEqual(aliases["PGUSER"], "postgres")
        self.assertEqual(aliases["PGDATABASE"], "clientes")
        self.assertEqual(aliases["DATABASE_URL"], PG_URI)

    def test_two_databases_of_the_same_engine_leave_the_short_name_out(self):
        """MONGO_URI no sabría a cuál de las dos apunta: mejor no publicarlo."""
        aliases = db_env.canonical_aliases([
            ("mongodb", {"URI": MONGO_URI}),
            ("mongodb", {"URI": "mongodb://otra:27017/x"}),
        ])
        self.assertNotIn("MONGO_URI", aliases)
        self.assertNotIn("DATABASE_URL", aliases)

    def test_generic_url_only_when_there_is_a_single_store(self):
        mixed = db_env.canonical_aliases([("mongodb", {"URI": MONGO_URI}), ("postgres", {"URI": PG_URI})])
        self.assertEqual(mixed["MONGO_URI"], MONGO_URI)
        self.assertEqual(mixed["POSTGRES_URI"], PG_URI)
        self.assertNotIn("DATABASE_URL", mixed)

    def test_a_cache_does_not_compete_for_database_url(self):
        with_cache = db_env.canonical_aliases([
            ("postgres", {"URI": PG_URI}),
            ("redis", {"URI": "redis://cache.prod.svc.cluster.local:6379/0"}),
        ])
        self.assertEqual(with_cache["DATABASE_URL"], PG_URI)
        self.assertEqual(with_cache["REDIS_URL"], "redis://cache.prod.svc.cluster.local:6379/0")

    def test_empty_components_are_skipped(self):
        aliases = db_env.canonical_aliases([("mongodb", {"URI": MONGO_URI, "PASSWORD": ""})])
        self.assertNotIn("MONGO_PASSWORD", aliases)


class ExistingAppTests(unittest.TestCase):
    """Apps ya desplegadas: el vínculo se reconoce en sus propias variables."""

    def test_north_star_bay_gets_mongo_uri(self):
        missing = db_env.missing_aliases(ORBIT_LITERALS)
        self.assertEqual(missing["MONGO_URI"], MONGO_URI)
        self.assertEqual(missing["MONGO_DATABASE"], "north_star_bay_api")
        self.assertNotIn("APP_SECRET", missing)

    def test_running_it_twice_changes_nothing(self):
        once = dict(ORBIT_LITERALS, **db_env.missing_aliases(ORBIT_LITERALS))
        self.assertEqual(db_env.missing_aliases(once), {})

    def test_an_app_that_already_defines_the_name_keeps_its_value(self):
        literals = dict(ORBIT_LITERALS, MONGO_URI="mongodb://mia:27017/x")
        missing = db_env.missing_aliases(literals)
        self.assertNotIn("MONGO_URI", missing)
        self.assertEqual(missing.get("MONGODB_URI"), MONGO_URI)

    def test_links_matrix_urls_also_count(self):
        """El vínculo genérico publica <ALIAS>_URL; una base sigue siendo una base."""
        missing = db_env.missing_aliases({
            "SHOP_BD_POSTGRES_URL": PG_URI,
            "SHOP_BD_POSTGRES_HOST": "h",
            "SHOP_BD_POSTGRES_PORT": "5432",
        })
        self.assertEqual(missing["PGHOST"], "h")
        self.assertEqual(missing["DATABASE_URL"], PG_URI)

    def test_a_plain_http_link_is_not_a_database(self):
        self.assertEqual(db_env.missing_aliases({"PAGOS_API_URL": "http://pagos-api.prod.svc.cluster.local:80"}), {})

    def test_secrets_without_bindings_produce_nothing(self):
        self.assertEqual(db_env.missing_aliases({"APP_SECRET": "x", "JWT_SECRET": "y"}), {})


OVERLAY = """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: prod
resources:
  - ../../base
images:
  - name: acme-dockerhub/north-star-bay-api
    newTag: prod-e526a82

# Generated secrets by Kaanbal Engine
secretGenerator:
  - name: north-star-bay-api-secrets
    behavior: replace
    literals:
      - APP_SECRET=ab=cd/ef+
      - NORTH_STAR_BAY_BD_URI=%s
      - NORTH_STAR_BAY_BD_HOST=north-star-bay-bd.prod.svc.cluster.local
generatorOptions:
  disableNameSuffixHash: false
""" % MONGO_URI


class OverlayParsingTests(unittest.TestCase):
    """Lo que ya inyecta el overlay es la única fuente para una app existente."""

    def test_reads_the_generated_literals(self):
        literals = db_env.parse_kustomize_literals(OVERLAY)
        self.assertEqual(literals["NORTH_STAR_BAY_BD_URI"], MONGO_URI)
        self.assertEqual(literals["NORTH_STAR_BAY_BD_HOST"], "north-star-bay-bd.prod.svc.cluster.local")

    def test_a_password_with_equals_keeps_its_value(self):
        self.assertEqual(db_env.parse_kustomize_literals(OVERLAY)["APP_SECRET"], "ab=cd/ef+")

    def test_stops_at_the_end_of_the_block(self):
        self.assertNotIn("generatorOptions", db_env.parse_kustomize_literals(OVERLAY))
        self.assertEqual(len(db_env.parse_kustomize_literals(OVERLAY)), 3)

    def test_an_overlay_without_secrets_yields_nothing(self):
        self.assertEqual(db_env.parse_kustomize_literals("resources:\n  - ../../base\n"), {})

    def test_parsed_overlay_feeds_the_repair(self):
        missing = db_env.missing_aliases(db_env.parse_kustomize_literals(OVERLAY))
        self.assertEqual(missing["MONGO_URI"], MONGO_URI)


if __name__ == "__main__":
    unittest.main()
