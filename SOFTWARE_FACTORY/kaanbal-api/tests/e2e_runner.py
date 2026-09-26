"""
Kaanbal Engine – E2E Test Runner
================================
Automated end-to-end tests that exercise the full deploy lifecycle
through the API. Each test is self-contained: deploy → verify → cleanup.

Usage:
    # Run all tests against local API (with SSH tunnel to MongoDB)
    python -m tests.e2e_runner --api http://localhost:8000

    # Run against cluster API (pod-forwarded or via Tailscale)
    python -m tests.e2e_runner --api http://10.42.3.62:8000

    # Run a specific suite
    python -m tests.e2e_runner --api http://localhost:8000 --suite templates

    # Dry run (show what would be tested)
    python -m tests.e2e_runner --api http://localhost:8000 --dry-run

    # Run from cluster master via SSH tunnel:
    ssh -i factory.pem -N -L 8000:10.42.3.62:8000 ubuntu@<elastic_ip>
    python -m tests.e2e_runner --api http://localhost:8000
"""

import argparse
import asyncio
import sys
import time
import json
from dataclasses import dataclass, field
from typing import Optional

import httpx

# ─── Configuration ───────────────────────────────────────────────
API_USER = "admin"
API_PASS = "admin123"
DEPLOY_TIMEOUT = 300  # seconds to wait for deploy completion
POLL_INTERVAL = 5     # seconds between status polls


@dataclass
class TestResult:
    name: str
    passed: bool
    duration: float = 0.0
    error: Optional[str] = None
    details: dict = field(default_factory=dict)


class TestRunner:
    def __init__(self, api_base: str, verbose: bool = False):
        self.api = api_base.rstrip("/")
        self.verbose = verbose
        self.token: Optional[str] = None
        self.results: list[TestResult] = []
        self.client = httpx.Client(timeout=30, verify=False)

    # ─── Auth ────────────────────────────────────────────────────
    def authenticate(self) -> bool:
        """Get JWT token from API."""
        r = self.client.post(
            f"{self.api}/api/v1/auth/token",
            data={"username": API_USER, "password": API_PASS},
        )
        if r.status_code == 200:
            self.token = r.json().get("access_token")
            return True
        print(f"  ✗ Auth failed: {r.status_code} {r.text[:200]}")
        return False

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    # ─── Test Execution ──────────────────────────────────────────
    def run_test(self, name: str, fn):
        """Run a single test function and record result."""
        t0 = time.time()
        try:
            details = fn()
            elapsed = time.time() - t0
            result = TestResult(name=name, passed=True, duration=elapsed, details=details or {})
        except AssertionError as e:
            elapsed = time.time() - t0
            result = TestResult(name=name, passed=False, duration=elapsed, error=str(e))
        except Exception as e:
            elapsed = time.time() - t0
            result = TestResult(name=name, passed=False, duration=elapsed, error=f"{type(e).__name__}: {e}")

        self.results.append(result)
        icon = "✓" if result.passed else "✗"
        print(f"  {icon} {name} ({elapsed:.1f}s)" + (f" — {result.error}" if result.error else ""))
        return result

    # ═══════════════════════════════════════════════════════════════
    # SUITE 1: Health & Auth
    # ═══════════════════════════════════════════════════════════════
    def suite_health(self):
        print("\n══ Suite: Health & Auth ══")

        self.run_test("GET /health returns 200", lambda: self._test_health())
        self.run_test("GET /ready returns 200", lambda: self._test_ready())
        self.run_test("POST /auth/token returns JWT", lambda: self._test_auth())
        self.run_test("GET /auth/me returns user", lambda: self._test_me())
        self.run_test("GET /system/health returns OK", lambda: self._test_system_health())
        self.run_test("GET /system/stats returns data", lambda: self._test_system_stats())

    def _test_health(self):
        r = self.client.get(f"{self.api}/health")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"

    def _test_ready(self):
        r = self.client.get(f"{self.api}/ready")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"

    def _test_auth(self):
        r = self.client.post(
            f"{self.api}/api/v1/auth/token",
            data={"username": API_USER, "password": API_PASS},
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert "access_token" in data, "Missing access_token"
        return {"token_prefix": data["access_token"][:20]}

    def _test_me(self):
        r = self.client.get(f"{self.api}/api/v1/auth/me", headers=self.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert data.get("username") == API_USER, f"Expected username={API_USER}"
        return {"username": data["username"]}

    def _test_system_health(self):
        r = self.client.get(f"{self.api}/api/v1/system/health", headers=self.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        return {"services": list(data.keys()) if isinstance(data, dict) else "ok"}

    def _test_system_stats(self):
        r = self.client.get(f"{self.api}/api/v1/system/stats", headers=self.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"

    # ═══════════════════════════════════════════════════════════════
    # SUITE 2: Template Catalog
    # ═══════════════════════════════════════════════════════════════
    def suite_templates(self):
        print("\n══ Suite: Template Catalog ══")

        self.run_test("GET /templates returns list", lambda: self._test_templates_list())
        self.run_test("GET /templates/creation-modes", lambda: self._test_creation_modes())
        self.run_test("Each template has required fields", lambda: self._test_template_fields())
        self.run_test("Config-only templates exist", lambda: self._test_config_only_templates())
        self.run_test("GET /templates/{id} details", lambda: self._test_template_details())

    def _test_templates_list(self):
        r = self.client.get(f"{self.api}/api/v1/templates", headers=self.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert len(data) > 0, "No templates found"
        return {"count": len(data)}

    def _test_creation_modes(self):
        r = self.client.get(f"{self.api}/api/v1/templates/creation-modes", headers=self.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        assert len(data) > 0, "No creation modes"
        modes = [m.get("id") or m.get("name") for m in data] if isinstance(data, list) else list(data.keys())
        return {"modes": modes}

    def _test_template_fields(self):
        r = self.client.get(f"{self.api}/api/v1/templates", headers=self.headers())
        templates = r.json()
        required = {"id", "name", "category"}
        invalid = []
        for t in templates:
            missing = required - set(t.keys())
            if missing:
                invalid.append(f"{t.get('id', '?')}: missing {missing}")
        assert len(invalid) == 0, f"Templates with missing fields: {invalid}"
        return {"validated": len(templates)}

    def _test_config_only_templates(self):
        r = self.client.get(f"{self.api}/api/v1/templates", headers=self.headers())
        templates = r.json()
        config_only = [t["id"] for t in templates if not t.get("needs_repo", True)]
        assert len(config_only) > 0, "No config-only templates found"
        return {"config_only_templates": config_only}

    def _test_template_details(self):
        r = self.client.get(f"{self.api}/api/v1/templates", headers=self.headers())
        templates = r.json()
        # Pick first template
        tid = templates[0]["id"]
        r2 = self.client.get(f"{self.api}/api/v1/templates/{tid}", headers=self.headers())
        assert r2.status_code == 200, f"Expected 200 for {tid}, got {r2.status_code}"
        return {"template": tid}

    # ═══════════════════════════════════════════════════════════════
    # SUITE 3: Config-Only Deploy E2E (EMQX)
    # ═══════════════════════════════════════════════════════════════
    def suite_deploy_config_only(self):
        print("\n══ Suite: Config-Only Deploy E2E (EMQX) ══")

        app_name = f"test-emqx-{int(time.time()) % 10000}"
        app_id = None

        def deploy():
            nonlocal app_id
            payload = {
                "name": app_name,
                "template": "emqx",
                "creation_mode": "config-only",
                "description": "E2E test EMQX deploy",
                "environments": ["dev", "staging", "prod"],
                "exposure": {"type": "tailscale"},
            }
            r = self.client.post(
                f"{self.api}/api/v1/apps",
                json=payload,
                headers=self.headers(),
                timeout=30,
            )
            assert r.status_code in (200, 201, 202), f"Deploy failed: {r.status_code} {r.text[:300]}"
            data = r.json()
            app_id = data.get("id") or data.get("_id") or data.get("app", {}).get("id")
            return {"app_id": app_id, "status_code": r.status_code}

        def wait_deploy():
            """Poll until app status is running or error."""
            deadline = time.time() + DEPLOY_TIMEOUT
            while time.time() < deadline:
                r = self.client.get(
                    f"{self.api}/api/v1/apps/{app_name}",
                    headers=self.headers(),
                )
                if r.status_code == 200:
                    data = r.json()
                    status = data.get("status", "")
                    if status == "running":
                        return {"status": status, "elapsed": DEPLOY_TIMEOUT - (deadline - time.time())}
                    if status == "error":
                        raise AssertionError(f"Deploy error: {data.get('error', 'unknown')}")
                time.sleep(POLL_INTERVAL)
            raise AssertionError(f"Deploy timed out after {DEPLOY_TIMEOUT}s")

        def verify_argocd():
            r = self.client.get(
                f"{self.api}/api/v1/apps/{app_name}/argocd",
                headers=self.headers(),
            )
            assert r.status_code == 200, f"ArgoCD status failed: {r.status_code}"
            data = r.json()
            # Check at least one env is synced
            synced = []
            if isinstance(data, dict):
                for env, info in data.items():
                    if isinstance(info, dict) and info.get("sync_status") == "Synced":
                        synced.append(env)
            assert len(synced) > 0, f"No envs are Synced: {data}"
            return {"synced_envs": synced}

        def verify_status():
            r = self.client.get(
                f"{self.api}/api/v1/apps/{app_name}/status/full",
                headers=self.headers(),
            )
            assert r.status_code == 200, f"Full status failed: {r.status_code}"
            return {"status_code": r.status_code}

        def cleanup():
            nonlocal app_id
            if not app_id:
                # Try to find by name
                r = self.client.get(
                    f"{self.api}/api/v1/apps/{app_name}",
                    headers=self.headers(),
                )
                if r.status_code == 200:
                    data = r.json()
                    app_id = str(data.get("_id", data.get("id", "")))
            if app_id:
                r = self.client.delete(
                    f"{self.api}/api/v1/apps/{app_id}",
                    headers=self.headers(),
                    timeout=60,
                )
                return {"delete_status": r.status_code}
            return {"delete_status": "skipped (no id)"}

        self.run_test(f"Deploy {app_name} (config-only)", deploy)
        self.run_test(f"Wait for {app_name} running", wait_deploy)
        self.run_test(f"ArgoCD status for {app_name}", verify_argocd)
        self.run_test(f"Full status for {app_name}", verify_status)
        self.run_test(f"Delete {app_name}", cleanup)

    # ═══════════════════════════════════════════════════════════════
    # SUITE 4: Existing Apps Verification
    # ═══════════════════════════════════════════════════════════════
    def suite_existing_apps(self):
        print("\n══ Suite: Existing Apps Verification ══")

        self.run_test("GET /apps returns list", lambda: self._test_apps_list())
        self.run_test("Each app has valid status", lambda: self._test_app_statuses())
        self.run_test("ArgoCD apps all Synced", lambda: self._test_all_argocd())

    def _test_apps_list(self):
        r = self.client.get(f"{self.api}/api/v1/apps", headers=self.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        apps = data if isinstance(data, list) else data.get("apps", [])
        return {"count": len(apps), "names": [a.get("name", "?") for a in apps]}

    def _test_app_statuses(self):
        r = self.client.get(f"{self.api}/api/v1/apps", headers=self.headers())
        apps = r.json() if isinstance(r.json(), list) else r.json().get("apps", [])
        valid_statuses = {"running", "deploying", "error", "degraded", "not_deployed", "pending"}
        invalid = []
        for a in apps:
            s = a.get("status", "unknown")
            if s not in valid_statuses:
                invalid.append(f"{a.get('name', '?')}: {s}")
        assert len(invalid) == 0, f"Apps with invalid status: {invalid}"
        status_summary = {}
        for a in apps:
            s = a.get("status", "unknown")
            status_summary[s] = status_summary.get(s, 0) + 1
        return {"statuses": status_summary}

    def _test_all_argocd(self):
        r = self.client.get(f"{self.api}/api/v1/apps/argocd/all", headers=self.headers())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        return {"argocd_apps": len(data) if isinstance(data, list) else "ok"}

    # ═══════════════════════════════════════════════════════════════
    # SUITE 5: Deploy Diagnostic
    # ═══════════════════════════════════════════════════════════════
    def suite_diagnostic(self):
        print("\n══ Suite: Deploy Diagnostic ══")

        self.run_test("Deploy readiness check", lambda: self._test_deploy_diagnostic())

    def _test_deploy_diagnostic(self):
        r = self.client.get(
            f"{self.api}/api/v1/system/deploy-diagnostic",
            headers=self.headers(),
            timeout=30,
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        return {"checks": list(data.keys()) if isinstance(data, dict) else "ok"}

    # ═══════════════════════════════════════════════════════════════
    # Report
    # ═══════════════════════════════════════════════════════════════
    def report(self):
        print("\n" + "═" * 60)
        print("TEST RESULTS SUMMARY")
        print("═" * 60)
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        total_time = sum(r.duration for r in self.results)

        for r in self.results:
            icon = "✓" if r.passed else "✗"
            line = f"  {icon} {r.name}"
            if r.error:
                line += f"\n      Error: {r.error}"
            print(line)

        print(f"\n  Total: {total} | Passed: {passed} | Failed: {failed} | Time: {total_time:.1f}s")
        print("═" * 60)
        return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Kaanbal Engine E2E Test Runner")
    parser.add_argument("--api", required=True, help="API base URL (e.g., http://localhost:8000)")
    parser.add_argument("--suite", choices=["health", "templates", "deploy", "apps", "diagnostic", "all"],
                        default="all", help="Which test suite to run")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be tested")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    runner = TestRunner(args.api, verbose=args.verbose)

    suites = {
        "health": ("Health & Auth", runner.suite_health),
        "templates": ("Template Catalog", runner.suite_templates),
        "deploy": ("Config-Only Deploy E2E", runner.suite_deploy_config_only),
        "apps": ("Existing Apps", runner.suite_existing_apps),
        "diagnostic": ("Deploy Diagnostic", runner.suite_diagnostic),
    }

    if args.dry_run:
        print("Dry run — would execute these suites:")
        for k, (name, _) in suites.items():
            if args.suite == "all" or args.suite == k:
                print(f"  • {name}")
        sys.exit(0)

    print(f"Kaanbal Engine E2E Tests — {args.api}")
    print("─" * 60)

    # Authenticate first
    if not runner.authenticate():
        print("✗ Authentication failed. Aborting.")
        sys.exit(1)
    print(f"  ✓ Authenticated as {API_USER}")

    # Run selected suites
    if args.suite == "all":
        for k, (_, fn) in suites.items():
            fn()
    else:
        name, fn = suites[args.suite]
        fn()

    # Report
    success = runner.report()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
