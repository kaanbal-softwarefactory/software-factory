"""Shared result type for independent exposure publishers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PublisherResult:
    """Typed outcome from Dns / Tailscale / Lan / GitOps / Bindings publishers."""

    name: str
    ok: bool
    status: str = "ok"  # ok | pending | skipped | failed
    attempts: int = 1
    detail: str = ""
    urls: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "status": self.status,
            "attempts": self.attempts,
            "detail": self.detail,
            "urls": list(self.urls),
            "meta": dict(self.meta),
        }


def merge_results(results: List[PublisherResult]) -> Dict[str, Any]:
    """Aggregate publisher results without dropping partial successes."""
    return {
        "ok": all(r.ok or r.status in ("pending", "skipped") for r in results),
        "critical_ok": all(
            r.ok or r.status == "skipped"
            for r in results
            if r.name in ("gitops", "bindings", "gitops_reconciler")
        ),
        "publishers": {r.name: r.to_dict() for r in results},
        "urls": [u for r in results for u in r.urls],
    }
