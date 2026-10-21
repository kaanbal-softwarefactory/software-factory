"""Business candidate acceptance: resource isolation, credential scope and kustomize."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import business_stack as bs, stack_launcher, change_plans

CATALOG = Path(__file__).resolve().parents[2] / "kaanbal-templates" / "catalog.json"


def plan(name="business-example", homepage=False):
    stack = next(s for s in json.loads(CATALOG.read_text(encoding="utf-8"))["stacks"] if s["id"] == "business-base-demo")
    return stack_launcher.build_plan(stack=stack, base_name=name, domain_fqdn="example.com", domain_id="demo",
                                     environments=["prod"], homepage=homepage)


def documents(component):
    return bs.render(component["template"], component["name"], component["template_config"], domain="example.com", image="business-base-image:pending")


class BusinessStackTests(unittest.TestCase):
    def test_explicit_modules_survive_rendering_including_empty_selection(self):
        for selected, expected in (([], []), (["appointments"], ["catalog", "appointments"]), (None, ["contact"])):
            web = plan()["components"][-1]
            web["template_config"].update(BUSINESS_PRESET="starter", BUSINESS_MODULES=selected)
            generated = documents(web)
            bootstrap = generated[0]["spec"]["template"]["spec"]["initContainers"][0]
            values = {e["name"]: e.get("value") for e in bootstrap["env"]}
            self.assertEqual(json.loads(values["BUSINESS_MODULES"]), expected)
        with self.assertRaises(ValueError):
            bs.normalize_modules("starter", ["payments"])

    def test_starter_pages_and_identity_callbacks_use_the_chosen_host(self):
        for homepage in (False, True):
            p = plan(homepage=homepage)
            for component in p["components"]:
                component["template_config"]["BUSINESS_PRESET"] = "starter"
            web = p["components"][-1]
            generated = documents(web)
            bootstrap = generated[0]["spec"]["template"]["spec"]["initContainers"][0]
            values = {e["name"]: e.get("value") for e in bootstrap["env"]}
            host = "example.com" if homepage else "business-example.example.com"
            self.assertEqual(values["APP_ORIGIN"], f"https://{host}")
            self.assertEqual(values["BUSINESS_PRESET"], "starter")
            pages = change_plans.stack_plan_view(p)["business"]["pages"]
            self.assertEqual(pages, {"landing": f"https://{host}/", "admin": f"https://{host}/admin", "client": f"https://{host}/client"})

    def test_order_and_private_database_with_real_ports(self):
        components = plan()["components"]
        self.assertEqual([c["role"] for c in components], ["database", "identity", "backend"])
        self.assertIsNone(components[0]["public_host"])
        for component, port in zip(components, [5432,8080,3000]):
            self.assertEqual(stack_launcher.app_create_payload(component)["specs"]["port"], port)

    def test_root_app_keeps_identity_on_its_own_host(self):
        p = plan(homepage=True)
        self.assertEqual(p["components"][-1]["public_host"], "example.com")
        self.assertEqual(p["components"][1]["public_host"], "business-example-identity.example.com")

    def test_copies_share_no_resource_names_or_secret_references(self):
        all_docs = [[d for c in plan(name)["components"] for d in documents(c)] for name in ["business-one", "business-two"]]
        names = [{d["metadata"]["name"] for d in docs} for docs in all_docs]
        self.assertFalse(names[0] & names[1])
        self.assertNotIn("business-one", json.dumps(all_docs[1]))

    def test_web_and_worker_never_receive_administrator_or_migrator_secrets(self):
        docs = documents(plan()["components"][-1])
        for d in docs:
            if d["kind"] != "Deployment":
                continue
            for c in d["spec"]["template"]["spec"]["containers"]:
                keys = {e["name"] for e in c["env"]}
                self.assertFalse(keys & {"MIGRATION_PGPASSWORD", "IDENTITY_ADMIN_PASSWORD", "OWNER_PASSWORD", "CUSTOMER_PASSWORD"})
        web = docs[0]["spec"]["template"]["spec"]
        self.assertFalse(web["automountServiceAccountToken"])
        self.assertIn("MIGRATION_PGPASSWORD", json.dumps(web["initContainers"]))
        self.assertEqual(web["containers"][0]["readinessProbe"]["httpGet"]["path"], "/api/ready")

    def test_identity_uses_production_mode_and_admin_is_not_public(self):
        docs = documents(plan()["components"][1])
        container = docs[0]["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["command"], ["/opt/keycloak/bin/kc.sh", "start"])
        ingress = next(d for d in docs if d["kind"] == "Ingress")
        paths = [p["path"] for p in ingress["spec"]["rules"][0]["http"]["paths"]]
        self.assertEqual(paths, ["/realms/", "/resources/"])

    def test_no_secret_values_or_public_mailbox_in_gitops(self):
        docs = [d for c in plan()["components"] for d in documents(c)]
        self.assertNotIn("Secret", {d["kind"] for d in docs})
        self.assertNotIn("secretGenerator", json.dumps(docs))
        public_names = {d["metadata"]["name"] for d in docs if d["kind"] == "Ingress"}
        self.assertFalse(any("mail" in n or "db" in n for n in public_names))
        pvc = next(d for d in docs if d["kind"] == "PersistentVolumeClaim")
        self.assertIn("Delete=false", pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"])

    def test_wrong_dependency_and_unsupported_environment_rejected(self):
        config = plan()["components"][0]["template_config"].copy()
        config["BUSINESS_DB_APP"] = "other-db"
        with self.assertRaises(ValueError):
            bs.validate_config("business-base", config, ["prod"])
        with self.assertRaises(ValueError):
            bs.validate_config("business-base", {}, ["dev", "prod"])

    def test_review_plan_binds_brand_and_source_revision(self):
        p = plan()
        for c in p["components"]:
            c["template_config"]["BUSINESS_SOURCE_SHA"] = "a" * 40
        before = change_plans.stack_plan_view(p)
        self.assertEqual(before["source_sha"], "a" * 40)
        self.assertEqual(before["business"]["preset"], "services")

    @unittest.skipUnless(shutil.which("kubectl") or shutil.which("kustomize"), "kustomize binary unavailable")
    def test_all_overlays_build_with_kustomize_and_update_all_app_processes(self):
        with tempfile.TemporaryDirectory() as root:
            for c in plan()["components"]:
                bs.write_overlay(root, c["template"], c["name"], c["template_config"], domain="example.com", dockerhub_user="example")
                overlay = Path(root) / "apps" / c["name"] / "overlays" / "prod"
                cmd = ["kubectl", "kustomize", str(overlay)] if shutil.which("kubectl") else ["kustomize", "build", str(overlay)]
                result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Secret\n", result.stdout)
                if c["template"] == "business-base":
                    self.assertNotIn("business-base-image:pending", result.stdout)
                    self.assertEqual(result.stdout.count("image: example/business-example:pending-initial-build"), 4)


if __name__ == "__main__":
    unittest.main()
