"""Variables de una app: qué se acepta, qué se protege y qué nunca se devuelve."""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.services import app_variables as av  # noqa: E402

BOUND = {
    "APP_SECRET": "x",
    "NORTH_STAR_BAY_BD_URI": "mongodb://u:p@north-star-bay-bd:27017/app?authSource=admin",
    "NORTH_STAR_BAY_BD_PASSWORD": "p",
    "NORTH_STAR_BAY_BD_HOST": "north-star-bay-bd",
    "MONGO_URI": "mongodb://u:p@north-star-bay-bd:27017/app?authSource=admin",
    "PUBLIC_ORIGINS": "https://shop.example.com",
}


class ResolveTests(unittest.TestCase):
    def test_a_generated_value_is_long_and_url_safe(self):
        wanted = av.resolve("ADMIN_PASSWORD", {"generate": True})
        self.assertTrue(wanted.generated)
        self.assertEqual(len(wanted.value), av.GENERATED_LENGTH)
        self.assertRegex(wanted.value, r"^[A-Za-z0-9_-]+$")
        self.assertNotEqual(wanted.value, av.resolve("ADMIN_PASSWORD", {"generate": True}).value)

    def test_only_a_generated_value_can_be_revealed(self):
        self.assertTrue(av.resolve("K", {"generate": True, "reveal": True}).reveal)
        self.assertFalse(av.resolve("K", {"value": "abc", "reveal": True}).reveal)
        self.assertFalse(av.resolve("K", {"generate": True}).reveal)

    def test_invalid_names(self):
        for name in ("admin_password", "1KEY", "KEY-NAME", "", "A" * 65):
            with self.assertRaises(av.VariableError, msg=name):
                av.resolve(name, {"value": "x"})

    def test_value_or_generate_not_both_not_neither(self):
        with self.assertRaises(av.VariableError):
            av.resolve("K", {"value": "x", "generate": True})
        with self.assertRaises(av.VariableError):
            av.resolve("K", {})

    def test_values_that_yaml_would_change_are_refused(self):
        for value in ("a\nb", "tab\there", " lead", "trail ", "a #comment", "key: value", "ends:", "", "x" * 5000):
            with self.assertRaises(av.VariableError, msg=repr(value)):
                av.resolve("K", {"value": value})

    def test_ordinary_values_are_accepted(self):
        for value in ("https://shop.example.com,https://www.shop.example.com", "sk_live_abc=123", "ñandú"):
            self.assertEqual(av.resolve("K", {"value": value}).value, value)

    def test_environments_must_be_a_list_of_names(self):
        self.assertEqual(av.resolve("K", {"value": "x", "environments": ["prod"]}).environments, ["prod"])
        with self.assertRaises(av.VariableError):
            av.resolve("K", {"value": "x", "environments": "prod"})


class PlanTests(unittest.TestCase):
    def test_a_new_variable_is_created_and_nothing_else_changes(self):
        state, literals = av.plan(BOUND, "ADMIN_PASSWORD", "s3cret-value-long", overwrite=False)
        self.assertEqual(state, av.CREATED)
        self.assertEqual({k: v for k, v in literals.items() if k != "ADMIN_PASSWORD"}, BOUND)

    def test_an_existing_variable_is_not_overwritten_by_accident(self):
        with self.assertRaises(av.VariableError):
            av.plan(BOUND, "PUBLIC_ORIGINS", "https://other.example.com", overwrite=False)
        state, literals = av.plan(BOUND, "PUBLIC_ORIGINS", "https://other.example.com", overwrite=True)
        self.assertEqual((state, literals["PUBLIC_ORIGINS"]), (av.UPDATED, "https://other.example.com"))

    def test_the_same_value_is_no_change(self):
        state, _ = av.plan(BOUND, "PUBLIC_ORIGINS", "https://shop.example.com", overwrite=False)
        self.assertEqual(state, av.UNCHANGED)

    def test_what_the_platform_writes_is_protected_even_with_overwrite(self):
        for name in ("MONGO_URI", "DATABASE_URL", "APP_SECRET", "NORTH_STAR_BAY_BD_PASSWORD", "NORTH_STAR_BAY_BD_HOST"):
            with self.assertRaises(av.VariableError, msg=name):
                av.plan(BOUND, name, "otro", overwrite=True)

    def test_a_prefix_that_is_not_a_database_is_not_protected(self):
        literals = {"STRIPE_URL": "https://api.stripe.com", "STRIPE_KEY": "k"}
        self.assertEqual(av.plan(literals, "STRIPE_KEY", "k2", overwrite=True)[0], av.UPDATED)


class HintTests(unittest.TestCase):
    def test_what_looks_like_a_secret(self):
        for name in ("ADMIN_PASSWORD", "JWT_SECRET", "GITHUB_TOKEN", "STRIPE_API_KEY", "PASSWORD_SALT"):
            self.assertTrue(av.looks_secret(name), name)
        for name in ("PUBLIC_ORIGINS", "LOG_LEVEL", "MONGO_DATABASE"):
            self.assertFalse(av.looks_secret(name), name)


if __name__ == "__main__":
    unittest.main()
