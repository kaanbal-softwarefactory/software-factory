"""Lectura del .env que trae el usuario.

Un .env escrito a mano mezcla estilos. Cuando el parser descartaba las claves en
minúscula, el instalador arrancaba "sin credenciales" y pedía a mano datos que el
usuario ya había entregado; el síntoma aparecía cinco pasos después, al fallar el
push a GitHub. Estos tests fijan esa tolerancia.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import parse_env_text  # noqa: E402


class ParseEnvTests(unittest.TestCase):
    def test_lowercase_keys_are_accepted(self):
        values = parse_env_text(
            "domain=acmeplatform.site\n"
            "github_org=acme-org\n"
            "docker_user=acme-dockerhub\n"
        )
        self.assertEqual(values["domain"], "acmeplatform.site")
        self.assertEqual(values["github_org"], "acme-org")
        self.assertEqual(values["docker_user"], "acme-dockerhub")

    def test_github_token_is_a_valid_alias_for_the_gitops_token(self):
        values = parse_env_text("github_token=ghp_example\n")
        self.assertEqual(values["gitops_token"], "ghp_example")

    def test_tailscale_dns_magic_alias(self):
        values = parse_env_text("tailscale_dns_magic=tail1234.ts.net\n")
        self.assertEqual(values["tailscale_dns"], "tail1234.ts.net")

    def test_export_prefix_and_quotes(self):
        values = parse_env_text('export DOMAIN="example.com"\n')
        self.assertEqual(values["domain"], "example.com")

    def test_empty_values_do_not_shadow_real_ones(self):
        # Un placeholder vacío no debe "ganarle" al valor que ya se tenía.
        values = parse_env_text("CF_TOKEN=\n# comentario\nDOMAIN=a.com\n")
        self.assertNotIn("cf_token", values)
        self.assertEqual(values["domain"], "a.com")

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(parse_env_text("MONGO_URI=mongodb://x\n"), {})

    def test_keys_that_merely_contain_export_are_untouched(self):
        values = parse_env_text("exported_domain=nope\nDOMAIN=si.com\n")
        self.assertEqual(values["domain"], "si.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)
