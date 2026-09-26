"""El id del túnel se deriva del token para guardarlo en la plataforma.

Sin ese id la API no puede cablear dominios adicionales: la instalación de laboratorio
quedó con "No hay túnel configurado" aunque el túnel estaba vivo.
"""
import base64
import json
import unittest

import server


def _token(payload):
    return base64.b64encode(json.dumps(payload).encode()).decode()


class TunnelIdFromTokenTests(unittest.TestCase):
    def test_reads_tunnel_id(self):
        token = _token({"a": "acct", "t": "tunnel-uuid", "s": "secreto"})
        self.assertEqual(server.tunnel_id_from_token(token), "tunnel-uuid")

    def test_tolerates_missing_padding(self):
        token = _token({"a": "acct", "t": "t1", "s": "x"}).rstrip("=")
        self.assertEqual(server.tunnel_id_from_token(token), "t1")

    def test_garbage_yields_empty_instead_of_raising(self):
        """Un token pegado mal no debe tumbar la instalación."""
        for bad in ("", None, "no-es-base64!!", _token(["lista"])):
            self.assertEqual(server.tunnel_id_from_token(bad), "")


if __name__ == "__main__":
    unittest.main()
