"""Tests de la instalación desatendida.

Todo lo que se comprueba aquí es lo que decide si la instalación arranca o se
detiene antes de tocar la máquina. Un fallo en esta capa es caro: o borra un
cluster con credenciales que no sirven, o rechaza un archivo perfectamente
válido.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unattended  # noqa: E402

COMPLETE = {
    "domain": "acmeplatform.site",
    "github_org": "acme-org",
    "gitops_token": "ghp_token",
    "docker_user": "acme-dockerhub",
    "docker_token": "dckr_pat_token",
    "cf_token": "cfut_token",
    "cf_account": "0123456789abcdef0123456789abcdef",
    "tailscale_id": "kOAuthId",
    "tailscale_secret": "tskey-secret",
    "tailscale_dns": "example.ts.net",
    "admin_user": "demo-admin",
    "admin_pass": "una-clave-larga-2026",
}


def normalize(**overrides):
    values = dict(COMPLETE)
    values.update(overrides)
    return unattended.normalize(values)


class DefaultsTests(unittest.TestCase):
    def test_domain_and_cloudflare_imply_cloud_mode(self):
        cfg, errors = normalize()
        self.assertEqual(errors, [])
        self.assertEqual(cfg["mode"], "cloud")
        self.assertEqual(cfg["console_exposure"], "public")
        self.assertEqual(cfg["api_exposure"], "public")

    def test_without_cloudflare_the_cell_stays_local(self):
        cfg, _ = normalize(cf_token="", cf_account="")
        self.assertEqual(cfg["mode"], "local")
        # En local no hay dominio público, así que el default seguro es la VPN.
        self.assertEqual(cfg["console_exposure"], "tailnet")

    def test_domain_is_cleaned_up(self):
        cfg, _ = normalize(domain="*.AcmePlatform.Site/")
        self.assertEqual(cfg["domain"], "acmeplatform.site")

    def test_admin_user_defaults_when_absent(self):
        cfg, _ = normalize(admin_user="")
        self.assertEqual(cfg["admin_user"], "admin")


class ValidationTests(unittest.TestCase):
    def test_short_admin_password_is_rejected_with_its_length(self):
        _, errors = normalize(admin_pass="Test123##")
        self.assertTrue(any("9 caracteres" in e for e in errors), errors)

    def test_missing_registry_credentials_are_reported(self):
        _, errors = normalize(docker_user="", docker_token="")
        self.assertTrue(any("DOCKER_USER" in e for e in errors), errors)

    def test_cloud_mode_requires_cloudflare(self):
        _, errors = normalize(mode="cloud", cf_token="")
        self.assertTrue(any("CF_TOKEN" in e for e in errors), errors)

    def test_cloud_mode_rejects_a_domain_that_is_not_one(self):
        _, errors = normalize(domain="no es un dominio")
        self.assertTrue(any("dominio válido" in e for e in errors), errors)

    def test_vpn_only_console_without_tailscale_is_refused(self):
        _, errors = normalize(console_exposure="tailnet",
                              tailscale_id="", tailscale_secret="")
        self.assertTrue(any("VPN" in e for e in errors), errors)

    def test_vpn_only_console_with_tailscale_is_fine(self):
        cfg, errors = normalize(console_exposure="tailnet")
        self.assertEqual(errors, [])
        self.assertEqual(cfg["console_exposure"], "tailnet")

    def test_unknown_exposure_is_rejected(self):
        _, errors = normalize(console_exposure="publico")
        self.assertTrue(any("KAANBAL_CONSOLE_EXPOSURE" in e for e in errors), errors)

    def test_local_mode_does_not_demand_a_domain(self):
        _, errors = normalize(mode="local", domain="", cf_token="", cf_account="")
        self.assertEqual(errors, [])


class AiProviderTests(unittest.TestCase):
    def test_a_key_becomes_a_provider_with_its_default_model(self):
        cfg, _ = normalize(deepseek_api_key="sk-abc")
        self.assertEqual(
            cfg["ai_providers"],
            [{"provider": "deepseek", "api_key": "sk-abc", "model": "deepseek-chat"}])

    def test_no_keys_means_no_agent_and_no_error(self):
        cfg, errors = normalize()
        self.assertEqual(cfg["ai_providers"], [])
        self.assertEqual(errors, [])


class EnvFileTests(unittest.TestCase):
    """El archivo real del usuario debe entenderse tal como lo escribe."""

    def test_hyphenated_agent_keys_configure_the_first_user(self):
        import server
        values = server.parse_env_text(
            "agente-user=demo-admin\nagente-password=una-clave-larga-2026\n")
        self.assertEqual(values["admin_user"], "demo-admin")
        self.assertEqual(values["admin_pass"], "una-clave-larga-2026")

    def test_deepseek_key_is_picked_up_in_lowercase(self):
        import server
        values = server.parse_env_text("deepseek_api_key=sk-abc\n")
        self.assertEqual(values["deepseek_api_key"], "sk-abc")

    def test_the_shipped_example_is_a_valid_starting_point(self):
        import server
        example = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.example")
        with open(example, encoding="utf-8") as handle:
            values = server.parse_env_text(handle.read())
        # Sin rellenar debe fallar, pero por credenciales ausentes y no porque
        # el archivo esté mal escrito o traiga una opción inválida.
        _, errors = unattended.normalize(values)
        self.assertTrue(errors)
        self.assertFalse([e for e in errors if "debe ser" in e], errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
