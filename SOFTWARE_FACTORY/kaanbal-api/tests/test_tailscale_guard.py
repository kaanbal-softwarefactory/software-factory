"""Dispositivos de la tailnet que la limpieza de huérfanos nunca toca."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import tailscale_guard as guard  # noqa: E402


class ProtectedPrefixTests(unittest.TestCase):
    def test_the_platform_devices_are_always_protected(self):
        for hostname in ("tailscale-operator", "tailscale-operator-0", "vault-ingress"):
            self.assertTrue(guard.is_protected(hostname, {}), hostname)
            self.assertTrue(guard.is_protected(hostname, None), hostname)

    def test_an_ordinary_device_is_not_protected(self):
        self.assertFalse(guard.is_protected("prod-mi-app-ts-ingress", {}))

    def test_the_installation_can_protect_its_own_machines(self):
        config = {"tailscale_protected_prefixes": ["portatil-ana"]}
        self.assertTrue(guard.is_protected("portatil-ana", config))

    def test_a_prefix_also_covers_the_names_tailscale_gives_duplicates(self):
        """Tras reinstalar, el mismo equipo aparece como 'equipo-1'."""
        config = {"tailscale_protected_prefixes": ["portatil-ana"]}
        self.assertTrue(guard.is_protected("portatil-ana-1", config))
        self.assertTrue(guard.is_protected("portatil-ana-2", config))
        self.assertFalse(guard.is_protected("portatil-luis", config))

    def test_a_comma_separated_text_works_as_well_as_a_list(self):
        got = guard.configured_prefixes({"tailscale_protected_prefixes": " uno , dos ,, uno "})
        self.assertEqual(got, ("uno", "dos"))

    def test_an_empty_prefix_would_protect_everything_so_it_is_dropped(self):
        got = guard.configured_prefixes({"tailscale_protected_prefixes": ["", "  ", "real"]})
        self.assertEqual(got, ("real",))
        self.assertFalse(guard.is_protected("prod-mi-app", {"tailscale_protected_prefixes": [""]}))

    def test_nonsense_in_the_configuration_never_breaks_the_cleanup(self):
        for value in (None, 5, {"a": 1}, True, [None], ["x" * 200]):
            got = guard.protected_prefixes({"tailscale_protected_prefixes": value})
            self.assertEqual(got[: len(guard.DEFAULT_PROTECTED_PREFIXES)], guard.DEFAULT_PROTECTED_PREFIXES)

    def test_the_default_does_not_name_any_person(self):
        """Antes había un nombre de máquina de una persona escrito en el código."""
        self.assertEqual(guard.DEFAULT_PROTECTED_PREFIXES, ("tailscale-operator", "vault-"))

    def test_platform_prefixes_are_not_duplicated_when_configured_again(self):
        got = guard.protected_prefixes({"tailscale_protected_prefixes": ["vault-", "mio"]})
        self.assertEqual(got, ("tailscale-operator", "vault-", "mio"))


if __name__ == "__main__":
    unittest.main()
