"""A generated repository must reproduce the approved launch choices locally."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import business_deployer as bd


class BusinessSourceTests(TestCase):
    def test_scaffold_persists_only_non_secret_local_configuration(self):
        def git(args, **kwargs):
            if args[1] == "init":
                source = Path(args[2]) / "SOFTWARE_FACTORY" / "business-base"
                (source / "scripts").mkdir(parents=True)
                (source / "scripts" / "provision-identity.mjs").write_text("// fixture")
                (source / "business.manifest.json").write_text('{"version":"0.1.0"}')
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as directory, patch.object(bd.subprocess, "run", side_effect=git):
            target = Path(directory) / "copy"
            bd.scaffold_source(target, {"BUSINESS_SOURCE_SHA": "a" * 40, "BUSINESS_APP": "example-starter",
                                       "BUSINESS_NAME": "Estudio Ejemplo", "BUSINESS_PRESET": "starter",
                                       "PGPASSWORD": "CHANGE_ME_NOT_COPIED"})
            config = json.loads((target / "business.config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["preset"], "starter")
            self.assertEqual(config["name"], "example-starter-local")
            self.assertEqual(config["title"], "Estudio Ejemplo")
            self.assertNotIn("CHANGE_ME_NOT_COPIED", json.dumps(config))
            self.assertEqual(json.loads((target / "business.manifest.json").read_text())["source_sha"], "a" * 40)
