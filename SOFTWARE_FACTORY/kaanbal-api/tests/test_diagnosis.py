"""Diagnóstico en lenguaje simple: cada regla, con fallas que pasaron de verdad.

Los tres primeros casos son una sola app real, en el orden en que apareció cada
error: primero le faltaba MONGO_URI; después, con la variable, la base rechazó
las credenciales (se había recreado sobre un disco viejo); por último pedía
ADMIN_PASSWORD. Durante días nadie lo supo porque la versión anterior seguía
atendiendo.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.modules.setdefault("app.db", types.SimpleNamespace(get_db=lambda: None))

from app.services import diagnosis  # noqa: E402

BINDING = ["APP_SECRET", "NORTH_STAR_BAY_BD_DATABASE", "NORTH_STAR_BAY_BD_HOST", "NORTH_STAR_BAY_BD_PASSWORD",
           "NORTH_STAR_BAY_BD_PORT", "NORTH_STAR_BAY_BD_URI", "NORTH_STAR_BAY_BD_USER"]

KEYERROR_MONGO = [
    'Traceback (most recent call last):',
    '  File "/app/main.py", line 18, in <module>',
    '    store = MongoStore()',
    '  File "/app/store.py", line 14, in __init__',
    "    self.client = MongoClient(os.environ['MONGO_URI'], serverSelectionTimeoutMS=10000)",
    '  File "<frozen os>", line 714, in __getitem__',
    "KeyError: 'MONGO_URI'",
]

AUTH_FAILED = [
    '  File "/usr/local/lib/python3.12/site-packages/pymongo/helpers_shared.py", line 250, in _check_command_response',
    '    raise OperationFailure(errmsg, code, response, max_wire_version)',
    "pymongo.errors.OperationFailure: Authentication failed., full error: {'ok': 0.0, 'errmsg': "
    "'Authentication failed.', 'code': 18, 'codeName': 'AuthenticationFailed'}",
    "ERROR:    Application startup failed. Exiting.",
]

KEYERROR_ADMIN = [
    '  File "/app/main.py", line 123, in lifespan',
    "    password = os.environ['ADMIN_PASSWORD']",
    '  File "<frozen os>", line 714, in __getitem__',
    "KeyError: 'ADMIN_PASSWORD'",
    "ERROR:    Application startup failed. Exiting.",
]


def stuck_bundle(lines, env_names=BINDING, databases=()):
    """Versión nueva en CrashLoopBackOff; la anterior sigue atendiendo."""
    return {
        "app": "north-star-bay-api", "namespace": "prod",
        "workload": {"exists": True, "kind": "Deployment", "desired": 1, "ready": 1, "updated": 1,
                     "conditions": [{"type": "Progressing", "status": "False", "reason": "ProgressDeadlineExceeded"}]},
        "revisions": [
            {"name": "api-old", "revision": 1, "image": "acme/north-star-bay-api:prod-4a5b6c7",
             "desired": 1, "ready": 1, "created": "2026-09-22T19:37:00+00:00"},
            {"name": "api-new", "revision": 2, "image": "acme/north-star-bay-api:prod-9f1c2d3",
             "desired": 1, "ready": 0, "created": "2026-09-22T20:10:00+00:00"},
        ],
        "pods": [
            {"name": "api-old-1", "owner": "api-old", "ready": True, "restarts": 1, "image": "acme/north-star-bay-api:prod-4a5b6c7"},
            {"name": "api-new-1", "owner": "api-new", "ready": False, "restarts": 1152,
             "image": "acme/north-star-bay-api:prod-9f1c2d3", "waiting_reason": "CrashLoopBackOff",
             "last_reason": "Error", "last_exit_code": 1},
        ],
        "events": [], "logs": {"pod": "api-new-1", "lines": list(lines)},
        "env_names": list(env_names), "ports": [8000],
        "probes": [{"kind": "readiness", "path": "/health", "port": 8000, "host_header": None}],
        "databases": list(databases),
    }


def codes(result):
    return [f["code"] for f in result["findings"]]


class RealIncidentTests(unittest.TestCase):
    def test_1_the_code_asks_for_mongo_uri_that_nobody_injects(self):
        result = diagnosis.analyze(stuck_bundle(KEYERROR_MONGO))
        self.assertEqual(result["status"], "problem")
        self.assertEqual(codes(result)[0], "missing_env_var")
        missing = result["findings"][0]
        self.assertEqual(missing["variable"], "MONGO_URI")
        self.assertEqual(missing["actions"][0]["id"], "repair_db_bindings")
        self.assertIn("MONGO_URI", result["summary"])

    def test_the_old_version_still_serving_is_explained(self):
        result = diagnosis.analyze(stuck_bundle(KEYERROR_MONGO))
        stuck = next(f for f in result["findings"] if f["code"] == "stuck_rollout")
        self.assertEqual(stuck["new_image"], "acme/north-star-bay-api:prod-9f1c2d3")
        self.assertEqual(stuck["serving_image"], "acme/north-star-bay-api:prod-4a5b6c7")
        self.assertIn("1152 reinicios", stuck["detail"])

    def test_2_the_database_rejects_credentials_on_a_volume_from_a_previous_life(self):
        database = {"name": "north-star-bay-bd", "volume_created": "2026-09-22T05:10:00+00:00",
                    "credentials_created": "2026-09-22T19:38:00+00:00"}
        result = diagnosis.analyze(stuck_bundle(AUTH_FAILED, env_names=BINDING + ["MONGO_URI"], databases=[database]))
        auth = result["findings"][0]
        self.assertEqual(auth["code"], "database_auth_failed")
        self.assertEqual(auth["database"], "north-star-bay-bd")
        self.assertIn("se volvió a crear con el mismo nombre", auth["detail"])
        self.assertEqual(auth["actions"], [], "reinicializar una base borra datos: nunca es un botón automático")

    def test_an_auth_failure_without_an_old_volume_does_not_blame_the_disk(self):
        database = {"name": "north-star-bay-bd", "volume_created": "2026-09-22T19:37:00+00:00",
                    "credentials_created": "2026-09-22T19:38:00+00:00"}
        result = diagnosis.analyze(stuck_bundle(AUTH_FAILED, databases=[database]))
        self.assertNotIn("mismo nombre", result["findings"][0]["detail"])

    def test_3_a_missing_admin_password_is_generated_not_invented(self):
        result = diagnosis.analyze(stuck_bundle(KEYERROR_ADMIN, env_names=BINDING + ["MONGO_URI"]))
        missing = result["findings"][0]
        self.assertEqual(missing["variable"], "ADMIN_PASSWORD")
        self.assertEqual(missing["actions"][0], {
            "id": "set_app_variable", "variable": "ADMIN_PASSWORD", "generate": True,
            "label": "Generar un valor seguro para ADMIN_PASSWORD",
        })

    def test_a_non_secret_variable_is_added_not_generated(self):
        lines = ["Error: Missing required environment variable: PUBLIC_ORIGINS"]
        action = diagnosis.analyze(stuck_bundle(lines))["findings"][0]["actions"][0]
        self.assertEqual((action["id"], action["generate"]), ("set_app_variable", False))


class RuleTests(unittest.TestCase):
    def pod_bundle(self, **pod):
        """Una sola versión, sin réplicas listas: aísla cada regla del caso de la versión atascada."""
        bundle = stuck_bundle([])
        bundle["revisions"] = []
        bundle["workload"]["conditions"] = []
        bundle["workload"]["ready"] = 0
        bundle["pods"] = [{"name": "api-1", "owner": "rs", "ready": False, "restarts": 0,
                           "image": "acme/api:prod-1", **pod}]
        return bundle

    def test_image_that_cannot_be_pulled(self):
        result = diagnosis.analyze(self.pod_bundle(waiting_reason="ImagePullBackOff",
                                                   waiting_message='Back-off pulling image "acme/api:prod-1"'))
        self.assertEqual(codes(result)[0], "image_pull")

    def test_a_missing_secret_offers_a_resync(self):
        result = diagnosis.analyze(self.pod_bundle(waiting_reason="CreateContainerConfigError",
                                                   waiting_message='secret "api-secrets-x" not found'))
        self.assertEqual(codes(result)[0], "config_error")
        self.assertEqual(result["findings"][0]["actions"][0]["id"], "sync_app")

    def test_out_of_memory(self):
        result = diagnosis.analyze(self.pod_bundle(restarts=3, last_reason="OOMKilled", waiting_reason="CrashLoopBackOff"))
        self.assertEqual(codes(result)[0], "out_of_memory")

    def test_a_missing_python_or_node_dependency(self):
        for line, module in (("ModuleNotFoundError: No module named 'jwt'", "jwt"),
                             ("Error: Cannot find module 'express'", "express")):
            bundle = self.pod_bundle(restarts=2, waiting_reason="CrashLoopBackOff")
            bundle["logs"]["lines"] = [line]
            finding = diagnosis.analyze(bundle)["findings"][0]
            self.assertEqual(finding["code"], "missing_dependency")
            self.assertIn(module, finding["title"])

    def test_listening_on_the_wrong_port(self):
        bundle = self.pod_bundle(restarts=0)
        bundle["logs"]["lines"] = ["INFO:     Uvicorn running on http://0.0.0.0:3000 (Press CTRL+C to quit)"]
        self.assertEqual(codes(diagnosis.analyze(bundle))[0], "port_mismatch")

    def test_the_right_port_is_not_reported(self):
        bundle = self.pod_bundle(restarts=0)
        bundle["logs"]["lines"] = ["INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)"]
        self.assertNotIn("port_mismatch", codes(diagnosis.analyze(bundle)))

    def test_a_health_check_rejected_by_a_host_filter(self):
        bundle = self.pod_bundle(restarts=0)
        bundle["events"] = [{"reason": "Unhealthy", "message": "Readiness probe failed: HTTP probe failed with statuscode: 403"}]
        finding = diagnosis.analyze(bundle)["findings"][0]
        self.assertEqual(finding["code"], "probe_rejected")
        self.assertIn("localhost", finding["detail"])

    def test_a_health_check_to_a_missing_route(self):
        bundle = self.pod_bundle(restarts=0)
        bundle["events"] = [{"reason": "Unhealthy", "message": "Liveness probe failed: HTTP probe failed with statuscode: 404"}]
        bundle["probes"].append({"kind": "liveness", "path": "/healthz", "port": 8000, "host_header": None})
        self.assertIn("/healthz", diagnosis.analyze(bundle)["findings"][0]["detail"])

    def test_an_unknown_crash_shows_the_log_and_the_final_error(self):
        bundle = self.pod_bundle(restarts=4, waiting_reason="CrashLoopBackOff")
        bundle["logs"]["lines"] = ["starting", "RuntimeError: la configuración del negocio no es válida", "bye"]
        finding = diagnosis.analyze(bundle)["findings"][0]
        self.assertEqual(finding["code"], "crash")
        self.assertIn("la configuración del negocio no es válida", finding["detail"])
        self.assertIn("starting", finding["evidence"])

    def test_pods_still_starting_without_errors(self):
        self.assertEqual(codes(diagnosis.analyze(self.pod_bundle(restarts=0))), ["starting"])


class StateTests(unittest.TestCase):
    def test_a_healthy_app_ignores_errors_left_in_old_logs(self):
        bundle = stuck_bundle(KEYERROR_MONGO)
        bundle["revisions"] = bundle["revisions"][1:]
        bundle["revisions"][0]["ready"] = 1
        bundle["workload"]["conditions"] = []
        bundle["pods"] = [{"name": "api-new-1", "owner": "api-new", "ready": True, "restarts": 3,
                           "image": "acme/north-star-bay-api:prod-9f1c2d3"}]
        result = diagnosis.analyze(bundle)
        self.assertEqual(result["status"], "ok")
        self.assertIn("Todo en orden", result["summary"])

    def test_a_stopped_app_is_not_a_problem(self):
        bundle = stuck_bundle([])
        bundle["workload"]["desired"] = 0
        self.assertIn("apagada", diagnosis.analyze(bundle)["summary"])

    def test_nothing_deployed_offers_a_sync(self):
        result = diagnosis.analyze({"app": "x", "namespace": "prod", "workload": {"exists": False}})
        self.assertEqual(codes(result), ["not_deployed"])
        self.assertEqual(result["findings"][0]["actions"][0]["id"], "sync_app")

    def test_a_variable_the_app_already_receives_is_not_missing(self):
        result = diagnosis.analyze(stuck_bundle(KEYERROR_MONGO, env_names=BINDING + ["MONGO_URI"]))
        self.assertNotIn("missing_env_var", codes(result))

    def test_a_dict_key_error_is_not_an_env_variable(self):
        result = diagnosis.analyze(stuck_bundle(["    payload = data['ID']", "KeyError: 'ID'"]))
        self.assertNotIn("missing_env_var", codes(result))


class SecrecyTests(unittest.TestCase):
    def test_masking(self):
        cases = {
            "mongodb://proadmin:S3cr3t@db:27017/app": "mongodb://proadmin:****@db:27017/app",
            "password=hunter22": "password=****",
            'MONGO_PASSWORD=hunter22': "MONGO_PASSWORD=****",
            '{"password": "hunter22"}': '{"password": "****"}',
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def": "Authorization: Bearer ****",
            "token kbl_0a1b2c_Secreto-123": "token kbl_****",
        }
        for raw, expected in cases.items():
            self.assertEqual(diagnosis.mask(raw), expected, raw)

    def test_code_that_reads_a_variable_is_not_mistaken_for_a_secret(self):
        line = "    password = os.environ['ADMIN_PASSWORD']"
        self.assertEqual(diagnosis.mask(line), line)

    def test_no_secret_reaches_the_evidence(self):
        lines = ["pymongo.errors.OperationFailure: Authentication failed. uri=mongodb://root:hunter22@db:27017"]
        result = diagnosis.analyze(stuck_bundle(lines, databases=[{"name": "db", "volume_created": None,
                                                                    "credentials_created": None}]))
        self.assertNotIn("hunter22", str(result))

    def test_binding_prefixes_come_from_the_variable_names(self):
        self.assertEqual(diagnosis.binding_prefixes(BINDING + ["MONGO_URI", "APP_SECRET"]), ["NORTH_STAR_BAY_BD"])


if __name__ == "__main__":
    unittest.main()
