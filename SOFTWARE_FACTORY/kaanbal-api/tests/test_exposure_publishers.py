"""Unit tests for exposure publishers (no cluster required)."""
from __future__ import annotations

import asyncio
import unittest

from app.services.exposure.orchestrator import ExposureOrchestrator
from app.services.exposure.retry import with_retries
from app.services.exposure.types import PublisherResult, merge_results


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_until_ok(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                return PublisherResult(name="x", ok=False, status="pending", detail="wait")
            return PublisherResult(name="x", ok=True, status="ok", detail="done")

        result = await with_retries(
            "x", flaky, attempts=5, base_delay=0.01, max_delay=0.05,
            retryable=lambda r: r.status == "pending",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(calls["n"], 3)


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_and_connection_info(self):
        order = []

        async def bindings():
            order.append("bindings")
            return PublisherResult(name="bindings", ok=True)

        async def gitops():
            order.append("gitops")
            return PublisherResult(name="gitops", ok=True)

        async def argo():
            order.append("argo")
            return PublisherResult(name="gitops_reconciler", ok=True)

        orch = ExposureOrchestrator()
        summary = await orch.apply_env(
            app_name="lab-api",
            env="dev",
            mode="tailscale",
            magic_hostname="dev-lab-api.example.ts.net",
            ensure_tailscale=True,
            bindings_fn=bindings,
            gitops_fn=gitops,
            argo_fn=argo,
        )
        self.assertEqual(order, ["bindings", "gitops", "argo"])
        self.assertEqual(summary["connection_info"]["tailscale_url"],
                         "http://dev-lab-api.example.ts.net")
        self.assertIn("cluster_url", summary["connection_info"])

    def test_merge_allows_pending_dns(self):
        merged = merge_results([
            PublisherResult(name="gitops", ok=True),
            PublisherResult(name="dns", ok=False, status="pending", detail="propagating"),
        ])
        self.assertTrue(merged["ok"])
        self.assertTrue(merged["critical_ok"])


if __name__ == "__main__":
    unittest.main()
