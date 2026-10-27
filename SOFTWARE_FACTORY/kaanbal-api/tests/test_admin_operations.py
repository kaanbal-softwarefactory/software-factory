"""Operación avanzada sin clúster: aprobaciones, versiones, datos, auditoría y reinicios.

Cada regla se prueba con las funciones puras. Lo que importa: nada irreversible
pasa sin una persona, ningún contenido del usuario llega crudo al shell del pod
y el diagnóstico explica un reinicio aunque Kubernetes no sepa la causa.
"""

import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.services import (agent_requests, app_operations, approvals, autonomy_catalog,  # noqa: E402
                          data_operations, diagnosis, permissions as perms, platform_audit, url_probe)
from app.services.autonomy_policy import AutonomyError  # noqa: E402


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 4, 12, 0)
        self.digest = approvals.fingerprint("host.execute", "nodo-1", {"command": "reboot"})
        self.doc = {"_id": "a" * 20, "digest": self.digest, "state": approvals.APPROVED,
                    "expires_at": self.now + timedelta(minutes=5)}

    def assertStatus(self, doc, status, digest=None):
        with self.assertRaises(AutonomyError) as caught:
            approvals.check(doc, digest or self.digest, self.now)
        self.assertEqual(caught.exception.status, status)

    def test_an_approved_matching_request_passes(self):
        approvals.check(self.doc, self.digest, self.now)

    def test_pending_rejected_used_expired_and_missing(self):
        self.assertStatus({**self.doc, "state": approvals.PENDING}, 428)
        self.assertStatus({**self.doc, "state": approvals.REJECTED}, 403)
        self.assertStatus({**self.doc, "state": approvals.USED}, 409)
        self.assertStatus({**self.doc, "expires_at": self.now - timedelta(seconds=1)}, 410)
        self.assertStatus(None, 404)

    def test_an_approval_does_not_cover_a_different_command(self):
        other = approvals.fingerprint("host.execute", "nodo-1", {"command": "rm -rf /"})
        self.assertStatus(self.doc, 409, digest=other)

    def test_the_fingerprint_is_stable_and_order_independent(self):
        self.assertEqual(approvals.fingerprint("x", "y", {"a": 1, "b": 2}), approvals.fingerprint("x", "y", {"b": 2, "a": 1}))

    def test_the_queue_is_on_unless_the_owner_turns_it_off(self):
        self.assertTrue(approvals.required_by(None))
        self.assertTrue(approvals.required_by({}))
        self.assertFalse(approvals.required_by({"approval_required": False}))

    def test_the_waiting_message_says_how_to_continue(self):
        error = approvals.ApprovalRequired({"_id": "b" * 20, "action": "data.restore", "target": "tienda-db/prod"})
        self.assertEqual(error.status, 428)
        self.assertIn("approval_id", str(error))
        self.assertIn("Acceso → Solicitudes", str(error))

    def test_the_upgrade_is_a_critical_capability(self):
        upgrade = next(t for t in autonomy_catalog.TOOLS if t["name"] == "platform_upgrade")
        self.assertTrue(upgrade["elevated"])
        for name in ("execute_app_command", "execute_node_command", "merge_app_pr", "platform_upgrade"):
            spec = next(t for t in autonomy_catalog.TOOLS if t["name"] == name)
            self.assertIn("approval_id", spec["body_args"], name)


class PermissionTests(unittest.TestCase):
    def test_new_endpoints_have_rules(self):
        cases = {
            ("GET", "/api/v1/apps/x/revisions"): "apps.apps.diagnose",
            ("POST", "/api/v1/apps/x/environments/prod/restart"): "apps.apps.deploy",
            ("POST", "/api/v1/apps/x/environments/prod/rollback"): "apps.releases.manage",
            ("POST", "/api/v1/apps/x/promote"): "apps.releases.manage",
            ("GET", "/api/v1/apps/x/probe"): "apps.apps.view",
            ("POST", "/api/v1/apps/x/backups/abc/restore"): "data.backups.restore",
            ("POST", "/api/v1/apps/x/query"): "data.records.read",
            ("POST", "/api/v1/secret-requests/abc/fulfill"): "apps.variables.manage",
            ("POST", "/api/v1/autonomy/approvals/abc/approve"): "autonomy.policy.manage",
            ("GET", "/api/v1/autonomy/approvals/abc"): "autonomy.tools.view",
        }
        for (method, path), permission in cases.items():
            self.assertEqual(perms.required_permission(method, path), (True, permission), path)

    def test_restoring_and_reading_data_are_critical(self):
        for key in ("data.backups.restore", "data.records.read"):
            self.assertEqual(perms.PERMISSIONS_BY_KEY[key].risk, perms.RISK_CRITICAL)

    def test_the_read_only_agent_cannot_change_releases_or_data(self):
        for key in ("apps.releases.manage", "data.backups.create", "data.backups.restore", "data.records.read"):
            self.assertNotIn(key, perms.AGENT_PERMISSIONS)


KUSTOMIZATION = """\
resources:
  - ../../base
images:
  - name: nginx:stable-alpine
    newName: acme/tienda
    newTag: prod-3f2a1c9 # lo escribe el pipeline
"""


class ReleaseTests(unittest.TestCase):
    def test_image_tags(self):
        self.assertEqual(app_operations.image_tag("docker.io/acme/tienda:prod-3f2a1c9"), "prod-3f2a1c9")
        self.assertEqual(app_operations.image_tag("registry:5000/acme/tienda"), "latest")
        self.assertEqual(app_operations.image_tag("acme/tienda@sha256:abc"), "sha256:abc")

    def test_the_tag_is_read_and_rewritten_keeping_the_comment(self):
        self.assertEqual(app_operations.read_tag(KUSTOMIZATION), "prod-3f2a1c9")
        text = app_operations.write_tag(KUSTOMIZATION, "prod-1a2b3c4")
        self.assertIn("newTag: prod-1a2b3c4 # lo escribe el pipeline", text)
        self.assertEqual(text.count("newTag"), 1)

    def test_a_tag_that_could_inject_yaml_is_refused(self):
        with self.assertRaises(app_operations.OperationError):
            app_operations.write_tag(KUSTOMIZATION, "x\nimages: []")
        with self.assertRaises(app_operations.OperationError):
            app_operations.write_tag("resources: []\n", "v1")

    def revisions(self):
        return app_operations.revisions_view([
            {"revision": 1, "image": "acme/tienda:prod-aaa", "ready": 0},
            {"revision": 2, "image": "acme/tienda:prod-bbb", "ready": 0},
            {"revision": 3, "image": "acme/tienda:prod-ccc", "ready": 1},
            {"revision": 4, "image": "acme/tienda:prod-bbb", "ready": 0},
        ], "prod-ccc")

    def test_revisions_newest_first_without_repeats(self):
        rows = self.revisions()
        self.assertEqual([r["tag"] for r in rows], ["prod-bbb", "prod-ccc", "prod-aaa"])
        self.assertTrue(next(r for r in rows if r["tag"] == "prod-ccc")["current"])

    def test_rollback_only_to_a_version_that_ran(self):
        plan = app_operations.rollback_plan("tienda", "prod", "prod-ccc", "prod-aaa", self.revisions())
        self.assertEqual((plan["from_tag"], plan["to_tag"]), ("prod-ccc", "prod-aaa"))
        for target in ("prod-zzz", "prod-ccc"):
            with self.assertRaises(app_operations.OperationError):
                app_operations.rollback_plan("tienda", "prod", "prod-ccc", target, self.revisions())

    def test_a_frontend_image_is_not_moved_between_environments(self):
        app = {"name": "web", "category": "frontend", "environments": ["staging", "prod"]}
        with self.assertRaises(app_operations.OperationError) as caught:
            app_operations.promote_plan(app, "staging", "prod", "staging-1", "prod-0")
        self.assertIn("rama", str(caught.exception))

    def test_a_backend_promotes_the_exact_image(self):
        app = {"name": "api", "category": "backend", "environments": ["staging", "prod"]}
        plan = app_operations.promote_plan(app, "staging", "prod", "staging-1", "prod-0")
        self.assertEqual((plan["from_tag"], plan["to_tag"]), ("prod-0", "staging-1"))

    def test_metrics_against_limits(self):
        view = app_operations.metrics_view(
            [{"pod": "api-1", "cpu": "450m", "memory": "230Mi"}],
            [{"name": "api-1", "ready": True, "restarts": 1, "cpu_limit": "500m", "memory_limit": "256Mi"},
             {"name": "api-2", "ready": True, "restarts": 0, "cpu_limit": None, "memory_limit": None}])
        first = view["pods"][0]
        self.assertEqual((first["cpu_pct"], first["memory_pct"]), (90, 90))
        self.assertTrue(any("memoria" in note and "api-1" in note for note in view["notes"]))
        self.assertTrue(any("sin límite" in note or "no tiene límite" in note for note in view["notes"]))

    def test_units(self):
        self.assertEqual(app_operations.millicores("12345678n"), 12.3)
        self.assertEqual(app_operations.millicores("1"), 1000.0)
        self.assertEqual(app_operations.mebibytes("1Gi"), 1024.0)
        self.assertEqual(app_operations.mebibytes("2048Ki"), 2.0)


class ProbeTests(unittest.TestCase):
    def test_certificate_close_to_expiry_warns(self):
        now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        cert = {"notAfter": "Oct 10 12:00:00 2026 GMT", "issuer": ((("organizationName", "Let's Encrypt"),),)}
        view = url_probe.tls_view(cert, now)
        self.assertEqual(view["days_left"], 6)
        self.assertTrue(view["warning"])
        self.assertEqual(view["issuer"], "Let's Encrypt")
        self.assertIn("vence en 6 días", url_probe.verdict({"status": 200, "latency_ms": 80, "tls": view}))

    def test_verdicts(self):
        self.assertIn("caída", url_probe.verdict({"status": 502}))
        self.assertIn("No responde", url_probe.verdict({"error": "ConnectTimeout"}))


class DataTests(unittest.TestCase):
    def test_only_known_engines(self):
        self.assertEqual(data_operations.engine_of({"template": "postgres"}), "postgres")
        self.assertEqual(data_operations.engine_of({"template": "mongodb"}), "mongodb")
        with self.assertRaises(data_operations.DataError):
            data_operations.engine_of({"name": "web", "template": "vue3-spa"})

    def test_reads_are_wrapped_with_a_row_limit(self):
        self.assertEqual(data_operations.sql_statement("select * from users;", 20),
                         "SELECT * FROM (select * from users) AS kaanbal_query LIMIT 20")
        self.assertEqual(data_operations.sql_statement("EXPLAIN select 1", 5), "EXPLAIN select 1")

    def test_writes_and_tricks_are_refused(self):
        for sql in ("delete from users", "select 1; drop table users", "update x set a=1",
                    "select pg_terminate_backend(1)", "with x as (select 1) select set_config('a','b',false)",
                    "select pg_read_file('/etc/passwd')", ""):
            with self.assertRaises(data_operations.DataError, msg=sql):
                data_operations.sql_statement(sql, 10)

    def test_user_content_never_reaches_the_shell_raw(self):
        sql = "select '$(rm -rf /)' as x, `id` as y"
        command = data_operations.sql_command(data_operations.sql_statement(sql, 5))
        self.assertNotIn("rm -rf", command)
        self.assertNotIn("`", command)
        self.assertIn("default_transaction_read_only=on", command)
        request = data_operations.mongo_request("find", collection="users", filter={"name": "\"; rm -rf / #"})
        mongo = data_operations.mongo_command(request)
        self.assertNotIn("rm -rf", mongo)

    def test_mongo_javascript_operators_are_refused(self):
        for bad in ({"$where": "sleep(1)"}, {"a": {"$function": {}}}, {"$or": [{"$where": "1"}]}):
            with self.assertRaises(data_operations.DataError):
                data_operations.mongo_request("find", collection="users", filter=bad)
        with self.assertRaises(data_operations.DataError):
            data_operations.mongo_request("drop", collection="users")

    def test_restore_reads_exactly_what_is_sent(self):
        command = data_operations.restore_command("postgres", 1234)
        self.assertTrue(command.split("; ", 1)[1].startswith("head -c 1234 | base64 -d | pg_restore"))
        self.assertIn("--drop", data_operations.restore_command("mongodb", 10))

    def test_restore_plan_only_from_a_finished_backup_of_the_same_base(self):
        app = {"name": "tienda-db"}
        good = {"_id": "x", "kind": "backup", "state": "succeeded", "app": "tienda-db", "env": "prod"}
        plan = data_operations.restore_plan(app, "prod", good)
        self.assertTrue(any("respaldo de seguridad" in effect for effect in plan["effects"]))
        for bad in ({**good, "state": "running"}, {**good, "kind": "restore"}, {**good, "app": "otra-db"}):
            with self.assertRaises(data_operations.DataError):
                data_operations.restore_plan(app, "prod", bad)

    def test_csv_rows(self):
        result = data_operations.csv_rows("id,name\n1,ana\n2,beto\n", 1)
        self.assertEqual(result, {"columns": ["id", "name"], "rows": [["1", "ana"]], "row_count": 2})


class SecretRequestTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(agent_requests.validate("STRIPE_KEY", "Cobros con tarjeta", None, ["dev", "prod"]), ["dev", "prod"])
        for args in (("stripe", "Cobros con tarjeta", None), ("STRIPE_KEY", "x", None), ("STRIPE_KEY", "Cobros", ["qa"])):
            with self.assertRaises(agent_requests.RequestError):
                agent_requests.validate(*args, ["dev", "prod"])


INVENTORY = [
    {"name": "brisa", "template": "vue3-spa", "group": "salon", "status": "running"},
    {"name": "brisa-salon-bd", "template": "mongodb", "group": "salon", "status": "running"},
    {"name": "brisa-salon-api", "template": "fastapi-api", "group": "plataforma", "status": "running"},
    {"name": "estrelamarina", "template": "vue3-spa", "group": "estrellamarina", "status": "running"},
    {"name": "laboratorio-bd", "template": "postgres", "group": "laboratorio", "status": "running"},
    {"name": "demo-web", "template": "vue3-spa", "group": None, "status": "error"},
]
LINKS = [{"from_app": "brisa-salon-api", "to_app": "brisa-salon-bd"}]


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        self.report = platform_audit.audit(
            INVENTORY, LINKS, health={"demo-web": "Degraded", "laboratorio-bd": "Healthy"},
            backups={"brisa-salon-bd": None, "laboratorio-bd": "2026-09-01T00:00:00Z"}, now=self.now)
        self.codes = {(f["code"], tuple(f["apps"])) for f in self.report["findings"]}

    def test_connected_pieces_in_different_groups(self):
        self.assertIn(("group_split", ("brisa-salon-api", "brisa-salon-bd")), self.codes)

    def test_a_typo_between_name_and_group(self):
        self.assertIn(("name_typo", ("estrelamarina",)), self.codes)

    def test_databases_without_use_or_backup(self):
        self.assertIn(("orphan_database", ("laboratorio-bd",)), self.codes)
        self.assertIn(("no_backup", ("brisa-salon-bd",)), self.codes)
        self.assertIn(("stale_backup", ("laboratorio-bd",)), self.codes)

    def test_errors_come_first(self):
        self.assertEqual(self.report["findings"][0]["severity"], platform_audit.ALTA)
        self.assertIn(("unhealthy", ("demo-web",)), self.codes)
        self.assertIn(("app_error", ("demo-web",)), self.codes)

    def test_a_tidy_platform_has_nothing_to_say(self):
        tidy = platform_audit.audit([{"name": "web", "template": "vue3-spa", "group": "web", "display_name": "Web"}], [])
        self.assertEqual(tidy["findings"], [])


class RestartDiagnosisTests(unittest.TestCase):
    def bundle(self, **pod):
        return {
            "app": "north-star-bay", "namespace": "prod",
            "workload": {"exists": True, "kind": "Deployment", "desired": 1, "ready": 1, "updated": 1, "conditions": []},
            "revisions": [{"name": "rs", "revision": 1, "image": "acme/north-star-bay:prod-3f2a1c9", "desired": 1, "ready": 1}],
            "pods": [{"name": "north-star-bay-7d9f8c6b5-x2k4p", "ready": True, "restarts": 1,
                      "image": "acme/north-star-bay:prod-3f2a1c9", "last_reason": "Unknown", "last_exit_code": None, **pod}],
            "events": [{"object": "north-star-bay-7d9f8c6b5-x2k4p", "type": "Warning", "reason": "SandboxChanged",
                        "message": "Pod sandbox changed, it will be killed and re-created.", "count": 1}],
            "logs": {"lines": ["nginx: worker process started"]},
        }

    def test_a_healthy_app_that_restarted_without_a_known_cause(self):
        result = diagnosis.analyze(self.bundle())
        self.assertEqual(result["status"], "ok")
        finding = result["findings"][0]
        self.assertEqual((finding["code"], finding["severity"]), ("restarted", diagnosis.INFO))
        self.assertIn("no registró la causa", finding["detail"])
        self.assertEqual(result["events"][0]["reason"], "SandboxChanged")

    def test_out_of_memory_restarts_are_not_just_info(self):
        result = diagnosis.analyze(self.bundle(last_reason="OOMKilled", last_exit_code=137, restarts=2))
        finding = result["findings"][0]
        self.assertEqual(finding["severity"], diagnosis.MEDIA)
        self.assertIn("memoria", finding["detail"])

    def test_no_restarts_no_finding(self):
        self.assertEqual(diagnosis.analyze(self.bundle(restarts=0))["findings"], [])


class DatabaseUsedByVariablesTests(unittest.TestCase):
    """Un stack conecta la base por variables <BASE>_URI y no deja un vínculo registrado."""

    APPS = [
        {"name": "tienda-api", "template": "fastapi-api", "group": "tienda", "environments": ["prod"], "status": "running"},
        {"name": "tienda-bd", "template": "postgres", "group": "tienda", "environments": ["prod"], "status": "running"},
        {"name": "vieja-db", "template": "postgres", "group": "vieja", "environments": ["prod"], "status": "running"},
    ]

    def codes(self, **kwargs):
        report = platform_audit.audit(self.APPS, [], **kwargs)
        return [(f["code"], tuple(f["apps"])) for f in report["findings"]]

    def test_a_database_an_app_reaches_through_its_variables_is_not_orphan(self):
        found = self.codes(variable_names={"tienda-api": ["APP_SECRET", "TIENDA_BD_URI", "TIENDA_BD_HOST"]})
        self.assertNotIn(("orphan_database", ("tienda-bd",)), found)
        self.assertIn(("orphan_database", ("vieja-db",)), found)

    def test_a_similar_name_is_not_enough(self):
        found = self.codes(variable_names={"tienda-api": ["TIENDA_URI", "OTRA_BD_URI"]})
        self.assertIn(("orphan_database", ("tienda-bd",)), found)

    def test_an_app_cannot_make_its_own_database_look_used(self):
        found = self.codes(variable_names={"tienda-bd": ["TIENDA_BD_URI"]})
        self.assertIn(("orphan_database", ("tienda-bd",)), found)

    def test_without_variable_names_it_still_flags_but_says_it_could_not_check(self):
        report = platform_audit.audit(self.APPS, [])
        detail = next(f["detail"] for f in report["findings"] if f["code"] == "orphan_database")
        self.assertIn("No se pudieron leer los nombres de variables", detail)


if __name__ == "__main__":
    unittest.main()
