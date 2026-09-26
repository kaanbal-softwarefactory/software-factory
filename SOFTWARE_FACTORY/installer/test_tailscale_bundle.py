"""Guard against a moving operator image outgrowing the vendored CRDs."""
from pathlib import Path
import re
import unittest


class TailscaleBundleTests(unittest.TestCase):
    def test_operator_proxy_and_overlay_match_crd_release(self):
        root = Path(__file__).parents[1] / "infra-gitops/apps/tailscale-operator"
        crds = (root / "base/crds.yaml").read_text(encoding="utf-8")
        release = re.search(r"Upstream: tailscale/tailscale (v\d+\.\d+\.\d+)", crds).group(1)
        deployment = (root / "base/deployment.yaml").read_text(encoding="utf-8")
        self.assertIn("image: tailscale/k8s-operator:" + release, deployment)
        self.assertIn("tailscale/tailscale:" + release, deployment)
        for overlay in (root / "overlays").glob("*/kustomization.yaml"):
            for tag in re.findall(r"newTag:\s*(\S+)", overlay.read_text(encoding="utf-8")):
                self.assertEqual(tag, release)
        self.assertNotIn(":stable", deployment)
        kinds = set(re.findall(r"^        kind: (\w+)$", crds, re.MULTILINE))
        self.assertEqual(kinds, {"Connector", "DNSConfig", "PeerRelay", "ProxyClass",
                                 "ProxyGroupPolicy", "ProxyGroup", "Recorder", "Tailnet"})


if __name__ == "__main__":
    unittest.main()
