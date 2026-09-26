"""Unit tests for ExposureSwitchService validation (no cluster)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.services.exposure.switch_service import ExposureSwitchService, VALID_MODES


class SwitchValidationTests(unittest.TestCase):
    def setUp(self):
        self.svc = ExposureSwitchService(MagicMock())

    def test_valid_modes_include_off_lan(self):
        self.assertIn("off", VALID_MODES)
        self.assertIn("lan", VALID_MODES)
        self.assertIn("tailscale", VALID_MODES)

    def test_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            self.svc.validate_modes("frontend", {"dev": "vpn-only"})

    def test_allows_off_for_frontend(self):
        self.svc.validate_modes("frontend", {"dev": "off", "prod": "public"})

    def test_rejects_public_database(self):
        with self.assertRaises(ValueError):
            self.svc.validate_modes("database", {"prod": "public"})

    def test_rejects_both_for_workflow(self):
        # v1: workflow usa un canal completo por ambiente (defaults.EXPOSURE_RULES);
        # el modo Mixed se retiró a propósito para n8n y este test quedó atrás.
        with self.assertRaises(ValueError):
            self.svc.validate_modes("workflow", {"prod": "both"})

    def test_allows_public_workflow_for_webhooks(self):
        self.svc.validate_modes("workflow", {"prod": "public"})


if __name__ == "__main__":
    unittest.main()
