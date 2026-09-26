"""La clave de firma de sesiones nunca es una que se pueda leer en el repositorio."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from app import config
    from app.defaults import SECRET_KEY_DEV
except ImportError:  # entorno sin las dependencias de la API
    config = None

needs_settings = unittest.skipIf(config is None, "pydantic-settings no está instalado (pip install -r requirements.txt)")


@needs_settings
class SigningKeyTests(unittest.TestCase):
    def test_a_configured_key_is_kept(self):
        self.assertEqual(config.ensure_signing_key("una-clave-larga-y-real"), "una-clave-larga-y-real")

    def test_without_a_key_each_process_gets_its_own(self):
        with mock.patch.object(config.logger, "warning") as warned:
            first = config.ensure_signing_key("")
            second = config.ensure_signing_key("")
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 48)
        self.assertEqual(warned.call_count, 2)

    def test_the_historical_development_key_is_no_longer_accepted(self):
        """Estaba escrita en el código: cualquiera podía firmar con ella."""
        got = config.ensure_signing_key(SECRET_KEY_DEV)
        self.assertNotEqual(got, SECRET_KEY_DEV)

    def test_the_loaded_settings_never_carry_the_historical_key(self):
        self.assertNotEqual(config.settings.SECRET_KEY, SECRET_KEY_DEV)
        self.assertTrue(config.settings.SECRET_KEY)


if __name__ == "__main__":
    unittest.main()
