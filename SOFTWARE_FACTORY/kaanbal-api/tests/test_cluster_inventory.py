import unittest

from app.services.cluster_inventory import assemble_inventory, parse_quantity


class ParseQuantityTests(unittest.TestCase):
    def test_cores_and_millis(self):
        self.assertEqual(parse_quantity("8"), 8.0)
        self.assertAlmostEqual(parse_quantity("558m"), 0.558)

    def test_memory(self):
        self.assertEqual(parse_quantity("1024Ki"), 1024 * 1024)
        self.assertEqual(parse_quantity("1Gi"), 1024**3)
        self.assertEqual(parse_quantity("3826Mi"), 3826 * 1024**2)


class AssembleInventoryTests(unittest.TestCase):
    def test_node_with_pod_and_metrics(self):
        nodes = {
            "items": [{
                "metadata": {
                    "name": "alice",
                    "labels": {"node-role.kubernetes.io/control-plane": "true"},
                },
                "status": {
                    "conditions": [
                        {"type": "Ready", "status": "True"},
                        {"type": "MemoryPressure", "status": "False"},
                        {"type": "DiskPressure", "status": "False"},
                    ],
                    "allocatable": {"cpu": "8", "memory": "7000Mi"},
                    "capacity": {"cpu": "8", "memory": "7000Mi"},
                    "addresses": [{"type": "InternalIP", "address": "192.168.1.50"}],
                    "nodeInfo": {
                        "osImage": "Ubuntu 26.04 LTS",
                        "kernelVersion": "7.0.0",
                        "kubeletVersion": "v1.36.2+k3s1",
                    },
                },
            }]
        }
        metrics = {
            "items": [{
                "metadata": {"name": "alice"},
                "usage": {"cpu": "558m", "memory": "3826Mi"},
            }]
        }
        pods = {
            "items": [{
                "metadata": {
                    "name": "stremingdogia-abc",
                    "namespace": "prod",
                    "labels": {"app": "stremingdogia"},
                },
                "spec": {"nodeName": "alice"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            }]
        }
        inv = assemble_inventory(nodes, metrics, pods)
        self.assertEqual(inv["node_count"], 1)
        node = inv["nodes"][0]
        self.assertEqual(node["name"], "alice")
        self.assertTrue(node["ready"])
        self.assertEqual(node["internal_ip"], "192.168.1.50")
        self.assertIsNone(node["battery"])
        self.assertEqual(node["pod_count"], 1)
        self.assertEqual(node["pods"][0]["app"], "stremingdogia")
        self.assertGreater(node["cpu"]["percent"], 0)
        self.assertGreater(node["memory"]["percent"], 0)
        self.assertFalse(node["pressure"]["memory"])


if __name__ == "__main__":
    unittest.main()
