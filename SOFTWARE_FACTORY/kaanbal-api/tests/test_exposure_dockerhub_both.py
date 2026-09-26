"""Contract tests that do not import heavy AppDeployer deps."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

DEPLOYER = Path(__file__).resolve().parents[1] / "app" / "services" / "app_deployer.py"


class DockerHubBothPathContract(unittest.TestCase):
    def setUp(self):
        self.src = DEPLOYER.read_text(encoding="utf-8")

    def test_dockerhub_calls_webhook_and_private_env(self):
        # Locate the docker-hub processor body
        m = re.search(
            r"async def _process_overlays_for_docker_hub\(.*?\n    def ",
            self.src,
            re.S,
        )
        self.assertIsNotNone(m, "could not find _process_overlays_for_docker_hub")
        body = m.group(0)
        self.assertIn("_generate_webhook_ingress", body)
        self.assertIn("_patch_env_domains_for_exposure", body)
        self.assertIn('env_exposure == "both"', body)

    def test_traefik_websocket_annotations_present(self):
        self.assertIn("_PROTOCOL_TRAEFIK_ANNOTATIONS", self.src)
        self.assertIn("traefik.ingress.kubernetes.io/service.sticky.cookie", self.src)
        self.assertIn("merged.update(_PROTOCOL_TRAEFIK_ANNOTATIONS", self.src)

    def test_ingress_tls_patch_gated_on_cluster_issuer(self):
        """Without issuer, overlays must not JSON-Patch /spec/tls (CF edge TLS)."""
        self.assertIn("def _ingress_host_json6902_ops", self.src)
        # Helper body gates TLS ops
        m = re.search(
            r"def _ingress_host_json6902_ops\(.*?\n    def ",
            self.src,
            re.S,
        )
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn("if self.ingress_cluster_issuer:", body)
        self.assertIn("/spec/tls/0/hosts/0", body)
        # Call sites use the helper (not unconditional TLS triples in overlays)
        self.assertGreaterEqual(self.src.count("_ingress_host_json6902_ops("), 3)


if __name__ == "__main__":
    unittest.main()
