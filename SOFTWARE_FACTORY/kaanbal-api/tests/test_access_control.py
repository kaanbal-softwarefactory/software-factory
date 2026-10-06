"""Control de acceso: catálogo, permisos efectivos y tokens personales.

La prueba que importa es la primera: **todo endpoint registrado tiene regla**.
La política es fail-closed, así que un endpoint sin regla queda inaccesible; sin
este test eso se descubriría en producción, con la consola rota.
"""

import os
import re
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.services import access  # noqa: E402
from app.services import permissions as perms  # noqa: E402

API = Path(__file__).resolve().parents[1]


def registered_endpoints():
    """(método, ruta) de cada endpoint, leídos del código como los registra main.py."""
    main = (API / "main.py").read_text(encoding="utf-8")
    prefixes = {}
    for line in main.split("\n"):
        match = re.search(r'include_router\((\w+)\.(\w+), prefix="([^"]+)"', line)
        if match:
            prefixes.setdefault(match.group(1), []).append((match.group(2), match.group(3)))
        bare = re.search(r'include_router\((\w+)\.(\w+), tags', line)
        if bare:
            prefixes.setdefault(bare.group(1), []).append((bare.group(2), ""))

    found = []
    for module, entries in prefixes.items():
        source = (API / "app" / "routers" / f"{module}.py").read_text(encoding="utf-8")
        for router_name, prefix in entries:
            pattern = rf'@{re.escape(router_name)}\.(get|post|put|patch|delete)\(\s*f?["\']([^"\']*)["\']'
            for match in re.finditer(pattern, source):
                path = prefix + match.group(2)
                if "..." in path:
                    continue  # ejemplo dentro de un docstring, no una ruta
                # Los parámetros llegan sin resolver al middleware: se sustituyen
                # por un valor realista (los ids de Mongo importan: el SSE del
                # deploy solo es público cuando el id lo es de verdad).
                concrete = re.sub(r"\{[a-z_]*id\}", "507f1f77bcf86cd799439011", path)
                concrete = re.sub(r"\{[^}]+\}", "ejemplo", concrete)
                found.append((match.group(1).upper(), path, concrete, module))
    return found


class CatalogCoverageTests(unittest.TestCase):
    def test_every_endpoint_is_covered(self):
        sin_regla = []
        for method, path, concrete, module in registered_endpoints():
            if perms.is_public(method, concrete) or perms.is_bootstrap(method, concrete):
                continue
            has_rule, _ = perms.required_permission(method, concrete)
            if not has_rule:
                sin_regla.append(f"{method} {path}  ({module})")
        self.assertEqual(
            sin_regla, [],
            "Endpoints sin regla ACL (quedarían bloqueados):\n  " + "\n  ".join(sin_regla),
        )

    def test_every_rule_points_to_a_real_permission(self):
        for item in perms.ACL_RULES:
            if item.permission is not None:
                self.assertIn(item.permission, perms.PERMISSION_KEYS, item.pattern)

    def test_every_permission_is_used_by_some_endpoint(self):
        """Un permiso que nadie exige es un permiso que engaña a quien lo asigna."""
        used = {item.permission for item in perms.ACL_RULES if item.permission}
        self.assertEqual(sorted(set(perms.PERMISSION_KEYS) - used), [])

    def test_the_deploy_stream_stays_public(self):
        """EventSource no manda cabeceras: el id de la app es la credencial."""
        self.assertTrue(perms.is_public("GET", "/api/v1/apps/507f1f77bcf86cd799439011/deploy/stream"))
        self.assertFalse(perms.is_public("GET", "/api/v1/apps/cualquiera/deploy/stream"))

    def test_login_and_webhooks_are_public(self):
        self.assertTrue(perms.is_public("POST", "/api/v1/auth/token"))
        self.assertTrue(perms.is_public("POST", "/api/v1/webhooks/deploy"))
        self.assertTrue(perms.is_public("GET", "/health"))

    def test_the_installer_is_only_open_before_the_first_account(self):
        self.assertTrue(perms.is_bootstrap("POST", "/api/v1/setup/install"))
        self.assertFalse(perms.is_public("POST", "/api/v1/setup/install"))
        has_rule, permission = perms.required_permission("POST", "/api/v1/setup/install")
        self.assertTrue(has_rule)
        self.assertEqual(permission, "setup.install.run")


class RuleResolutionTests(unittest.TestCase):
    """Las rutas literales tienen que ganarle a las paramétricas."""

    def test_literal_routes_win(self):
        self.assertEqual(perms.required_permission("GET", "/api/v1/apps/argocd/all")[1], "apps.apps.view")
        self.assertEqual(perms.required_permission("POST", "/api/v1/apps/mi-app/argocd/sync")[1], "apps.apps.deploy")

    def test_reading_is_not_the_same_as_changing(self):
        self.assertEqual(perms.required_permission("GET", "/api/v1/apps/x/domain")[1], "apps.apps.view")
        self.assertEqual(perms.required_permission("POST", "/api/v1/apps/x/domain")[1], "apps.apps.expose")
        self.assertEqual(perms.required_permission("DELETE", "/api/v1/apps/x")[1], "apps.apps.delete")

    def test_secrets_and_credentials_are_their_own_permission(self):
        self.assertEqual(perms.required_permission("GET", "/api/v1/system/vault/secrets")[1], "system.secrets.view")
        self.assertEqual(perms.required_permission("GET", "/api/v1/system/credentials/raw")[1], "system.credentials.manage")

    def test_an_unknown_endpoint_has_no_rule(self):
        self.assertEqual(perms.required_permission("POST", "/api/v1/algo/nuevo"), (False, None))


class EffectivePermissionTests(unittest.TestCase):
    OWNER = {"slug": "owner", "superadmin": True, "permissions": []}
    LECTOR = {"slug": "lector", "superadmin": False, "permissions": ["apps.apps.view", "domains.domains.view"]}

    def test_an_owner_can_do_everything(self):
        granted = access.effective_permissions({"username": "alice"}, [self.OWNER])
        self.assertEqual(granted, set(perms.PERMISSION_KEYS))

    def test_roles_add_up(self):
        extra = {"slug": "x", "superadmin": False, "permissions": ["stacks.stacks.launch"]}
        granted = access.effective_permissions({"username": "a"}, [self.LECTOR, extra])
        self.assertIn("apps.apps.view", granted)
        self.assertIn("stacks.stacks.launch", granted)

    def test_a_denial_beats_everything_including_owner(self):
        """La única forma de decir 'puede todo menos borrar apps'."""
        user = {"username": "bob", "permission_overrides": {"apps.apps.delete": "deny"}}
        granted = access.effective_permissions(user, [self.OWNER])
        self.assertNotIn("apps.apps.delete", granted)
        self.assertIn("apps.apps.create", granted)

    def test_a_grant_adds_a_single_permission(self):
        user = {"username": "carol", "permission_overrides": {"core.updates.apply": "allow"}}
        granted = access.effective_permissions(user, [self.LECTOR])
        self.assertIn("core.updates.apply", granted)

    def test_a_suspended_account_can_do_nothing(self):
        granted = access.effective_permissions({"username": "x", "disabled": True}, [self.OWNER])
        self.assertEqual(granted, set())

    def test_invented_permissions_are_ignored(self):
        role = {"slug": "raro", "superadmin": False, "permissions": ["apps.apps.view", "apps.apps.destroy_world"]}
        granted = access.effective_permissions({"username": "x"}, [role])
        self.assertEqual(granted, {"apps.apps.view"})


class SystemRoleTests(unittest.TestCase):
    ROLES = {role["slug"]: role for role in perms.SYSTEM_ROLES}

    def test_the_agent_role_can_look_but_not_touch(self):
        granted = access.role_permissions([self.ROLES["agente"]])
        self.assertIn("apps.apps.view", granted)
        self.assertIn("apps.apps.diagnose", granted)
        for forbidden in ("apps.apps.delete", "system.secrets.view", "system.credentials.view",
                          "core.updates.apply", "security.users.manage", "apps.apps.create"):
            self.assertNotIn(forbidden, granted, forbidden)

    def test_an_operator_runs_the_platform_but_not_its_keys(self):
        granted = access.role_permissions([self.ROLES["operador"]])
        self.assertIn("apps.apps.create", granted)
        self.assertIn("stacks.stacks.launch", granted)
        for forbidden in ("system.credentials.manage", "system.secrets.view", "core.updates.apply",
                          "security.users.manage", "setup.install.run", "logs.records.purge"):
            self.assertNotIn(forbidden, granted, forbidden)

    def test_a_reader_never_changes_anything(self):
        for key in access.role_permissions([self.ROLES["lector"]]):
            action = key.rsplit(".", 1)[-1]
            self.assertIn(action, ("view", "self"), key)

    def test_legacy_accounts_keep_working(self):
        self.assertEqual(perms.LEGACY_ROLE_MAP["admin"], "owner")
        self.assertEqual(perms.LEGACY_ROLE_MAP["user"], "operador")


class PersonalTokenTests(unittest.TestCase):
    def test_a_token_is_never_stored_in_clear(self):
        raw, prefix, stored = access.generate_token()
        self.assertTrue(raw.startswith("kbl_"))
        self.assertIn(prefix, raw)
        self.assertNotIn(stored, raw)
        self.assertTrue(access.token_matches(raw, stored))
        self.assertFalse(access.token_matches(raw + "x", stored))

    def test_the_prefix_finds_the_row_without_revealing_the_secret(self):
        raw, prefix, _ = access.generate_token()
        self.assertEqual(access.token_prefix(raw), prefix)
        # El secreto puede contener "_": se corta solo en los dos primeros.
        self.assertNotIn(raw.split("_", 2)[2], prefix)

    def test_a_token_is_told_apart_from_a_session(self):
        raw, _, _ = access.generate_token()
        self.assertTrue(access.looks_like_token(raw))
        self.assertFalse(access.looks_like_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.x.y"))

    def test_a_token_never_grants_more_than_its_owner(self):
        owner = {"apps.apps.view", "apps.apps.create"}
        self.assertEqual(
            access.scoped_permissions(owner, ["apps.apps.view", "core.updates.apply"]),
            {"apps.apps.view"},
        )

    def test_without_scopes_it_inherits_what_the_person_can_do(self):
        owner = {"apps.apps.view"}
        self.assertEqual(access.scoped_permissions(owner, []), owner)
        self.assertEqual(access.scoped_permissions(owner, None), owner)

    def test_revoked_and_expired_tokens_stop_working(self):
        self.assertTrue(access.token_is_usable({"expires_at": datetime.utcnow() + timedelta(days=1)}))
        self.assertFalse(access.token_is_usable({"revoked_at": datetime.utcnow()}))
        self.assertFalse(access.token_is_usable({"expires_at": datetime.utcnow() - timedelta(seconds=1)}))
        self.assertTrue(access.token_is_usable({"expires_at": None}))

    def test_what_is_shown_of_a_token_has_no_secret(self):
        raw, prefix, stored = access.generate_token()
        view = access.token_view({
            "_id": "1", "name": "mcp", "username": "alice", "prefix": prefix,
            "token_hash": stored, "scopes": ["apps.apps.view"], "created_at": datetime.utcnow(),
        })
        self.assertNotIn("token_hash", view)
        self.assertEqual(view["state"], "activo")
        self.assertNotIn(raw, str(view))

    def test_invented_scopes_are_dropped(self):
        self.assertEqual(
            access.validate_scopes(["apps.apps.view", "no.existe.nada"]),
            ["apps.apps.view"],
        )


class PrincipalTests(unittest.TestCase):
    def test_can_answers_the_acl_question(self):
        principal = access.Principal(username="a", permissions={"apps.apps.view"})
        self.assertTrue(principal.can("apps.apps.view"))
        self.assertFalse(principal.can("apps.apps.delete"))
        self.assertTrue(principal.can(None))  # endpoint que solo pide sesión

    def test_a_principal_knows_if_it_came_from_a_token(self):
        self.assertFalse(access.Principal(username="a").via_token)
        self.assertTrue(access.Principal(username="a", token_id="1", token_name="mcp").via_token)


if __name__ == "__main__":
    unittest.main()
