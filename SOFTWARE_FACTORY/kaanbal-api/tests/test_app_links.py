"""Vincular apps (app/services/app_links.py): qué variables llegan y qué nunca se pisa."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import app_links  # noqa: E402

API = {"name": "tienda-api", "template": "fastapi-api", "category": "backend", "environments": ["dev", "prod"]}
DB = {"name": "tienda-db", "template": "mongodb", "category": "database", "environments": ["dev", "prod"]}
PAGOS = {"name": "pagos-api", "template": "fastapi-api", "category": "backend", "environments": ["prod"]}


class KindAndAliasTests(unittest.TestCase):
    def test_a_database_is_recognized_by_template_or_category(self):
        self.assertEqual(app_links.kind_of(DB), "database")
        self.assertEqual(app_links.kind_of({"name": "x", "template": "custom", "category": "database"}), "database")
        self.assertEqual(app_links.kind_of(PAGOS), "service")

    def test_the_default_alias_is_the_other_app_in_capitals(self):
        self.assertEqual(app_links.alias_for("tienda-db"), "TIENDA_DB")
        self.assertEqual(app_links.alias_for("tienda-db", "principal"), "PRINCIPAL")

    def test_an_alias_that_is_not_a_variable_prefix_is_refused(self):
        for alias in ("1BASE", "MI-BASE", "A B", "X" * 60):
            with self.assertRaises(app_links.LinkError):
                app_links.alias_for("tienda-db", alias)


class EnvironmentTests(unittest.TestCase):
    def test_by_default_the_shared_environments(self):
        self.assertEqual(app_links.environments_for(API, PAGOS), ["prod"])
        self.assertEqual(app_links.environments_for(API, DB), ["dev", "prod"])

    def test_an_environment_the_other_app_lacks_is_explained(self):
        with self.assertRaises(app_links.LinkError) as ctx:
            app_links.environments_for(API, PAGOS, ["dev"])
        self.assertIn("pagos-api", str(ctx.exception))

    def test_no_shared_environment_means_no_link(self):
        with self.assertRaises(app_links.LinkError):
            app_links.environments_for({**API, "environments": ["dev"]}, PAGOS)

    def test_the_link_goes_from_the_user_to_the_database(self):
        with self.assertRaises(app_links.LinkError):
            app_links.check_pair(DB, API)
        with self.assertRaises(app_links.LinkError):
            app_links.check_pair(API, API)
        app_links.check_pair(API, DB)


class VariablesTests(unittest.TestCase):
    def test_a_service_link_gives_the_in_cluster_address(self):
        variables = app_links.service_variables("pagos-api", "prod", "PAGOS_API", 8000)
        self.assertEqual(variables, {
            "PAGOS_API_HOST": "pagos-api.prod.svc.cluster.local",
            "PAGOS_API_PORT": "8000",
            "PAGOS_API_URL": "http://pagos-api.prod.svc.cluster.local:8000",
        })

    def test_database_credentials_that_were_not_found_stop_the_link(self):
        with self.assertRaises(app_links.LinkError):
            app_links.check_database_variables("tienda-db", "prod", "TIENDA_DB", "mongodb",
                                               {"TIENDA_DB_HOST": "h", "TIENDA_DB_URI": "mongodb://h"})
        app_links.check_database_variables("tienda-db", "prod", "TIENDA_DB", "mongodb",
                                           {"TIENDA_DB_PASSWORD": "p", "TIENDA_DB_URI": "mongodb://u:p@h"})
        # Redis puede no tener contraseña.
        app_links.check_database_variables("cache", "prod", "CACHE", "redis", {"CACHE_URI": "redis://h:6379/0"})


class MergeTests(unittest.TestCase):
    def test_new_names_are_added(self):
        merged, added, kept = app_links.merge({"APP_SECRET": "s"}, {"PAGOS_API_URL": "http://p"}, "PAGOS_API")
        self.assertEqual(merged, {"APP_SECRET": "s", "PAGOS_API_URL": "http://p"})
        self.assertEqual((added, kept), (["PAGOS_API_URL"], []))

    def test_linking_again_changes_nothing(self):
        current = {"PAGOS_API_URL": "http://p"}
        merged, added, kept = app_links.merge(current, {"PAGOS_API_URL": "http://p"}, "PAGOS_API")
        self.assertEqual((merged, added, kept), (current, [], ["PAGOS_API_URL"]))

    def test_standard_names_that_already_exist_are_respected(self):
        """Una segunda base del mismo motor no le cambia MONGO_URI a la app."""
        current = {"MONGO_URI": "mongodb://primera"}
        merged, added, kept = app_links.merge(
            current, {"MONGO_URI": "mongodb://segunda", "SEGUNDA_URI": "mongodb://segunda"}, "SEGUNDA",
        )
        self.assertEqual(merged["MONGO_URI"], "mongodb://primera")
        self.assertEqual(added, ["SEGUNDA_URI"])
        self.assertEqual(kept, ["MONGO_URI"])

    def test_a_prefixed_name_with_another_value_is_never_overwritten(self):
        with self.assertRaises(app_links.LinkError) as ctx:
            app_links.merge({"PAGOS_API_URL": "http://otro"}, {"PAGOS_API_URL": "http://p"}, "PAGOS_API")
        self.assertIn("alias", str(ctx.exception))

    def test_remove_takes_only_what_is_there(self):
        remaining, removed = app_links.remove({"A": "1", "B": "2"}, ["B", "C"])
        self.assertEqual((remaining, removed), ({"A": "1"}, ["B"]))


if __name__ == "__main__":
    unittest.main()
