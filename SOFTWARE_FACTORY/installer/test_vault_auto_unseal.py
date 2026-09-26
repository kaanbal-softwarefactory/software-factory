"""Desbloqueo automático de Vault tras un reinicio del nodo.

Caso real (laboratorio, 2026-09-21): el nodo se reinició, Vault quedó sellado y un
despliegue no pudo guardar los secretos de su base de datos.
"""
import json
import os
import tempfile
import unittest

import vault_bootstrap as vb


class FakeVault:
    """Simula `k3s kubectl exec ... vault` sin clúster."""

    def __init__(self, *, initialized=True, sealed=True, reachable=True):
        self.initialized = initialized
        self.sealed = sealed
        self.reachable = reachable
        self.unseal_calls = 0

    def __call__(self, args, input_text=None):
        joined = " ".join(args)
        if "vault status" in joined:
            if not self.reachable:
                return 1, "error: pod not ready"
            return (2 if self.sealed else 0), json.dumps(
                {"initialized": self.initialized, "sealed": self.sealed})
        if "operator unseal" in joined:
            self.unseal_calls += 1
            self.sealed = False
            return 0, ""
        if "secrets list" in joined:
            return 0, json.dumps({"secret/": {"type": "kv", "options": {"version": "2"}}})
        return 0, ""


class AutoUnsealTests(unittest.TestCase):
    def setUp(self):
        fd, self.recovery = tempfile.mkstemp()
        with os.fdopen(fd, "w") as fh:
            json.dump({"root_token": "root", "unseal_keys_b64": ["key"]}, fh)

    def tearDown(self):
        os.unlink(self.recovery)

    def test_unseals_a_sealed_vault(self):
        vault = FakeVault(sealed=True)
        message = vb.auto_unseal(run=vault, recovery_path=self.recovery)
        self.assertEqual(vault.unseal_calls, 1)
        self.assertFalse(vault.sealed)
        self.assertIn("desbloqueado", message)

    def test_is_silent_when_vault_is_open(self):
        """Corre cada 2 minutos: no debe tocar nada ni llenar el journal."""
        vault = FakeVault(sealed=False)
        self.assertIsNone(vb.auto_unseal(run=vault, recovery_path=self.recovery))
        self.assertEqual(vault.unseal_calls, 0)

    def test_waits_while_vault_is_still_booting(self):
        vault = FakeVault(reachable=False)
        self.assertIsNone(vb.auto_unseal(run=vault, recovery_path=self.recovery))

    def test_never_initializes_a_fresh_vault(self):
        """Inicializar genera claves nuevas: decisión humana, nunca de un timer."""
        vault = FakeVault(initialized=False, sealed=True)
        self.assertIsNone(vb.auto_unseal(run=vault, recovery_path=self.recovery))
        self.assertEqual(vault.unseal_calls, 0)

    def test_sealed_without_recovery_file_is_reported(self):
        vault = FakeVault(sealed=True)
        with self.assertRaises(RuntimeError):
            vb.auto_unseal(run=vault, recovery_path=self.recovery + ".missing")


if __name__ == "__main__":
    unittest.main()
