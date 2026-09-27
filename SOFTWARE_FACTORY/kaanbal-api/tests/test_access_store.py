"""Migración de cuentas anteriores al catálogo de roles (access_store.ensure_seed).

La cuenta que crea el instalador (POST /setup/install) no tiene `role`, solo
`is_superuser=True`. Sin esto, ensure_seed() la mandaba al rol "operador" y
perdía core.updates.apply y el resto de permisos de dueño: la primera cuenta
de toda instalación real quedaba sin poder actualizar el core ni gestionar
usuarios, y sin nadie con permiso para arreglarlo desde la consola.

Standalone: py tests/test_access_store.py
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.ModuleType("app.db"))
sys.modules["app.db"].get_db = lambda: None

from app.services import access_store  # noqa: E402
from app.services import permissions as perms  # noqa: E402


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


class FakeUsers:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        if query == {"roles": {"$exists": False}}:
            matched = [d for d in self.docs if "roles" not in d]
        else:
            matched = list(self.docs)
        return FakeCursor(matched)

    async def update_one(self, filt, update, **kw):
        for doc in self.docs:
            if doc.get("_id") == filt.get("_id"):
                doc.update(update.get("$set", {}))
                return


class FakeRoles:
    def __init__(self):
        self.docs = {}

    async def update_one(self, filt, update, **kw):
        doc = self.docs.setdefault(filt["slug"], {})
        doc.update(update.get("$set", {}))


class FakeDb:
    def __init__(self, user_docs):
        self._collections = {"users": FakeUsers(user_docs), "roles": FakeRoles()}

    def __getitem__(self, name):
        return self._collections[name]


def seed(user_docs):
    db = FakeDb(user_docs)
    access_store.get_db = lambda: db
    import asyncio
    asyncio.run(access_store.ensure_seed())
    return db


class BootstrapAccountMigrationTests(unittest.TestCase):
    def test_the_installer_bootstrap_account_becomes_owner(self):
        db = seed([{"_id": 1, "username": "andres", "is_superuser": True}])
        user = db["users"].docs[0]
        self.assertEqual(user["roles"], ["owner"])
        self.assertTrue(user["superadmin"])

    def test_a_legacy_admin_role_string_becomes_owner_too(self):
        db = seed([{"_id": 2, "username": "old-admin", "role": "admin"}])
        user = db["users"].docs[0]
        self.assertEqual(user["roles"], ["owner"])
        self.assertTrue(user["superadmin"])

    def test_a_legacy_plain_user_becomes_operador_not_owner(self):
        db = seed([{"_id": 3, "username": "op", "role": "user"}])
        user = db["users"].docs[0]
        self.assertEqual(user["roles"], ["operador"])
        self.assertFalse(user["superadmin"])

    def test_is_superuser_wins_even_if_role_says_user(self):
        """No debería pasar en la práctica, pero is_superuser es la señal fuerte."""
        db = seed([{"_id": 4, "username": "x", "role": "user", "is_superuser": True}])
        user = db["users"].docs[0]
        self.assertEqual(user["roles"], ["owner"])

    def test_accounts_already_migrated_are_left_alone(self):
        db = seed([{"_id": 5, "username": "y", "roles": ["lector"], "is_superuser": True}])
        user = db["users"].docs[0]
        self.assertEqual(user["roles"], ["lector"])
        self.assertNotIn("superadmin", user)

    def test_system_roles_are_seeded_regardless_of_users(self):
        db = seed([])
        slugs = {role["slug"] for role in perms.SYSTEM_ROLES}
        self.assertEqual(set(db["roles"].docs.keys()), slugs)
        self.assertTrue(db["roles"].docs["owner"]["superadmin"])


if __name__ == "__main__":
    unittest.main()
