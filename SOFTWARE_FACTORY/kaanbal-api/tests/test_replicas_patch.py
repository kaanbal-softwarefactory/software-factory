"""Unit tests for replica patch workload detection (Deployment vs StatefulSet)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from app.services.exposure.switch_service import ExposureSwitchService


class ReplicasPatchTests(unittest.TestCase):
    def setUp(self):
        self.svc = ExposureSwitchService(MagicMock())

    def _layout(self, *, kind: str):
        root = tempfile.mkdtemp(prefix="kb-replicas-")
        base = os.path.join(root, "base")
        overlay = os.path.join(root, "overlays", "staging")
        os.makedirs(base)
        os.makedirs(overlay)
        with open(os.path.join(base, "workload.yaml"), "w", encoding="utf-8") as fh:
            fh.write(
                f"apiVersion: apps/v1\nkind: {kind}\nmetadata:\n  name: test-vue\n"
            )
        with open(os.path.join(overlay, "kustomization.yaml"), "w", encoding="utf-8") as fh:
            fh.write("resources:\n  - ../../base\npatchesStrategicMerge: []\n")
        return overlay

    def test_frontend_writes_only_deployment_patch(self):
        overlay = self._layout(kind="Deployment")
        self.svc._write_replicas_patch(overlay, "test-vue", 1)
        self.assertTrue(os.path.isfile(os.path.join(overlay, "patch-replicas.yaml")))
        self.assertFalse(os.path.isfile(os.path.join(overlay, "patch-replicas-sts.yaml")))
        kust = open(os.path.join(overlay, "kustomization.yaml"), encoding="utf-8").read()
        self.assertIn("patch-replicas.yaml", kust)
        self.assertNotIn("patch-replicas-sts.yaml", kust)

    def test_database_writes_statefulset_patch(self):
        overlay = self._layout(kind="StatefulSet")
        self.svc._write_replicas_patch(overlay, "lab-mongo", 1)
        self.assertTrue(os.path.isfile(os.path.join(overlay, "patch-replicas-sts.yaml")))
        self.assertFalse(os.path.isfile(os.path.join(overlay, "patch-replicas.yaml")))

    def test_removes_stale_sts_patch_on_deployment_app(self):
        overlay = self._layout(kind="Deployment")
        stale = os.path.join(overlay, "patch-replicas-sts.yaml")
        with open(stale, "w", encoding="utf-8") as fh:
            fh.write("kind: StatefulSet\n")
        kust_path = os.path.join(overlay, "kustomization.yaml")
        with open(kust_path, "a", encoding="utf-8") as fh:
            fh.write("  - patch-replicas-sts.yaml\n")
        self.svc._write_replicas_patch(overlay, "test-vue", 2)
        self.assertFalse(os.path.isfile(stale))
        kust = open(kust_path, encoding="utf-8").read()
        self.assertNotIn("patch-replicas-sts.yaml", kust)


if __name__ == "__main__":
    unittest.main()
