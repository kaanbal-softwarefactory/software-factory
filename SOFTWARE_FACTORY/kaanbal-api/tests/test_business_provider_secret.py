"""Provider capture never rewrites managed database secrets or serializes values."""
import asyncio
import ast
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import app_variables, business_provider_secret as service


class ProviderSecretTests(unittest.TestCase):
    def test_reference_is_bounded_and_contains_no_credential(self):
        value = "CHANGE_ME_PROVIDER_KEY"
        item = service.descriptor("b" * 46, value)
        self.assertLessEqual(len(item["secret_name"]), 63)
        self.assertNotIn(value, json.dumps(item))
        self.assertFalse(item["delivery_enabled"])
        self.assertNotEqual(item, service.descriptor("b" * 46, "CHANGE_ME_ROTATED_KEY"))
        self.assertNotEqual(item, service.descriptor("b" * 45 + "c", value))

    def test_rotation_requires_explicit_overwrite(self):
        old = service.descriptor("example-business", "CHANGE_ME_OLD")
        new = service.descriptor("example-business", "CHANGE_ME_NEW")
        self.assertEqual(service.plan_descriptor(old, old), app_variables.UNCHANGED)
        with self.assertRaises(app_variables.VariableError):
            service.plan_descriptor(old, new)
        self.assertEqual(service.plan_descriptor(old, new, True), app_variables.UPDATED)

    def test_refuses_platform_credentials_and_other_environments_before_side_effects(self):
        deployer = types.SimpleNamespace(_load_credentials=AsyncMock())
        for variable, envs in [("PGPASSWORD", ["prod"]), ("OIDC_CLIENT_SECRET", ["prod"]),
                               ("SENDGRID_API_KEY", ["staging"])]:
            with self.assertRaises(app_variables.VariableError):
                asyncio.run(service.store_credential(deployer, "example-business", variable, "CHANGE_ME", envs))
        deployer._load_credentials.assert_not_awaited()

    def run_capture(self, *, failed_vault=False, fresh_workspace=False):
        key = "CHANGE_ME_PROVIDER_KEY"
        with tempfile.TemporaryDirectory() as directory:
            pushed = []
            async def push(path, *args, **kwargs):
                files = {str(p.relative_to(path)): p.read_text() for p in Path(path).rglob("*") if p.is_file()}
                pushed.append(files)
            workspace = str(Path(directory) / "after-restart") if fresh_workspace else directory
            deployer = types.SimpleNamespace(workspace=workspace, _load_credentials=AsyncMock(),
                provider=types.SimpleNamespace(get_auth_clone_url=lambda _: "https://example.com/infra.git"),
                _push_infra=push)
            def clone(args, **kwargs):
                root = Path(args[-1])
                overlay = root / "apps/example-business/overlays/prod"
                overlay.mkdir(parents=True)
                (overlay / "kustomization.yaml").write_text("resources:\n- ../../base\n")
                base = root / "apps/example-business/base"
                base.mkdir(parents=True)
                (base / "resources.yaml").write_text("existing database and runtime secret references")
            vault = AsyncMock(side_effect=RuntimeError(key)) if failed_vault else AsyncMock(return_value={"SENDGRID_API_KEY": key})
            with patch.object(service.subprocess, "run", clone), \
                 patch.object(service.business_deployer, "_vault_credentials", vault), \
                 patch.object(service.business_deployer, "materialize_secret") as materialize:
                if failed_vault:
                    with self.assertRaises(app_variables.VariableError) as caught:
                        asyncio.run(service.store_credential(deployer, "example-business", "SENDGRID_API_KEY", key, ["prod"]))
                    self.assertNotIn(key, str(caught.exception))
                    self.assertIn("etapa: Vault", str(caught.exception))
                    self.assertEqual(pushed, [])
                    materialize.assert_not_called()
                else:
                    result = asyncio.run(service.store_credential(deployer, "example-business", "SENDGRID_API_KEY", key, ["prod"]))
                    self.assertNotIn(key, json.dumps(result))
                    self.assertEqual(len(pushed), 1)
                    self.assertNotIn(key, json.dumps(pushed))
                    self.assertEqual(next(v for p, v in pushed[0].items() if p.endswith("kustomization.yaml")),
                                     "resources:\n- ../../base\n")
                    self.assertTrue(any(p.endswith("provider-credential.json") for p in pushed[0]))
                    self.assertEqual(materialize.call_args.args[1], {"SENDGRID_API_KEY": key})
                    self.assertTrue(vault.await_args.args[1].startswith("example-business/providers/sendgrid/"))

    def test_capture_publishes_only_descriptor_and_preserves_existing_manifests(self):
        self.run_capture()

    def test_vault_failure_is_sanitized_and_does_not_publish(self):
        self.run_capture(failed_vault=True)

    def test_first_capture_after_restart_creates_its_workspace(self):
        self.run_capture(fresh_workspace=True)


class VariableHandlerTests(unittest.TestCase):
    def handler(self, template):
        from fastapi import Depends, HTTPException
        path = Path(__file__).resolve().parents[1] / "app/routers/apps.py"
        function = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                        if isinstance(n, ast.AsyncFunctionDef) and n.name == "set_app_variable")
        function.decorator_list = []
        self.legacy = AsyncMock()
        deployer = types.SimpleNamespace(set_app_variable=self.legacy)
        app = {"name": "example-business", "environments": ["prod"], "template": template}
        self.find = AsyncMock(return_value=app)
        self.log = AsyncMock()
        namespace = {"Depends": Depends, "HTTPException": HTTPException, "User": object,
            "get_current_active_user": lambda: None,
            "get_db": lambda: types.SimpleNamespace(apps=types.SimpleNamespace(find_one=self.find)),
            "AppDeployer": lambda: deployer,
            "activity_log": types.SimpleNamespace(log=self.log), "CATEGORY_APP": "app"}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        return namespace["set_app_variable"]

    def test_managed_capture_never_calls_legacy_writer_or_returns_the_value(self):
        handler = self.handler("business-base")
        report = {"environments": {"prod": app_variables.CREATED}, "committed": True,
                  "storage": "vault_runtime_secret", "message": "stored privately"}
        with patch.object(service, "store_credential", AsyncMock(return_value=report)) as secure:
            answer = asyncio.run(handler("example-business", "SENDGRID_API_KEY", {"value": "CHANGE_ME"},
                                         types.SimpleNamespace(username="owner")))
        secure.assert_awaited_once()
        self.legacy.assert_not_awaited()
        self.assertNotIn("CHANGE_ME", json.dumps(answer))
        self.assertNotIn("CHANGE_ME", str(self.log.await_args))
        self.assertEqual(answer["message"], "stored privately")
        self.assertEqual(self.find.await_args.args[1]["template"], 1)

    def test_managed_database_rejects_generic_variable_mutation(self):
        from fastapi import HTTPException
        handler = self.handler("business-postgres")
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(handler("example-business", "SENDGRID_API_KEY", {"value": "CHANGE_ME"},
                                types.SimpleNamespace(username="owner")))
        self.assertEqual(caught.exception.status_code, 409)
        self.legacy.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
