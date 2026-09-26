"""Los manifiestos incrustados en el instalador deben ser YAML válido.

`CLOUDFLARED_DEPLOYMENT` llevaba llaves dobles heredadas de una plantilla de
`str.format()`. Como el texto se escribe tal cual, el YAML resultante era
inválido, kubectl lo rechazaba, nadie miraba el código de salida y el paso se
declaraba "Túnel activo". El síntoma final era un HTTP 530 en todo el dominio,
a cinco pasos de distancia de la causa.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None

EMBEDDED = {
    "CLOUDFLARED_DEPLOYMENT": server.CLOUDFLARED_DEPLOYMENT,
}


class EmbeddedManifestTests(unittest.TestCase):
    def test_no_unformatted_template_braces(self):
        for name, text in EMBEDDED.items():
            with self.subTest(manifest=name):
                self.assertNotIn("{{", text,
                                 f"{name} conserva llaves de plantilla sin formatear")

    @unittest.skipIf(yaml is None, "PyYAML no está disponible")
    def test_manifests_parse_as_yaml(self):
        for name, text in EMBEDDED.items():
            with self.subTest(manifest=name):
                document = yaml.safe_load(text)
                self.assertIsInstance(document, dict, f"{name} no es un documento")
                self.assertIn("kind", document)

    @unittest.skipIf(yaml is None, "PyYAML no está disponible")
    def test_cloudflared_reads_its_token_from_the_secret(self):
        document = yaml.safe_load(server.CLOUDFLARED_DEPLOYMENT)
        container = document["spec"]["template"]["spec"]["containers"][0]
        source = container["env"][0]["valueFrom"]["secretKeyRef"]
        self.assertEqual(source["name"], "cloudflared-secrets")
        self.assertEqual(source["key"], "TUNNEL_TOKEN")
        # Las etiquetas deben ser cadenas: un mapa anidado aquí es exactamente
        # lo que producía el manifiesto inválido.
        for key, value in document["metadata"]["labels"].items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
