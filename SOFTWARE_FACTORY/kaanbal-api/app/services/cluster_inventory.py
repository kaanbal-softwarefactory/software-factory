"""Cluster node + pod inventory for the Kaanbal console fleet panel."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.exposure.probes import in_cluster, k8s_get

logger = logging.getLogger(__name__)

_QUANTITY_RE = re.compile(r"^([0-9]*\.?[0-9]+)([a-zA-Z]*)$")

_BIN = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "Pi": 1024**5}
_DEC = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}


def parse_quantity(raw: Any) -> float:
    """Parse Kubernetes resource quantities to a float (cores or bytes)."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return 0.0
    match = _QUANTITY_RE.match(text)
    if not match:
        try:
            return float(text)
        except ValueError:
            return 0.0
    value = float(match.group(1))
    suffix = match.group(2)
    if not suffix:
        return value
    if suffix in _BIN:
        return value * _BIN[suffix]
    if suffix in _DEC:
        return value * _DEC[suffix]
    return value


def _condition_map(conditions: List[dict]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in conditions or []:
        ctype = item.get("type")
        if ctype:
            out[ctype] = str(item.get("status") or "")
    return out


def _allocatable(status: dict) -> Tuple[float, float]:
    alloc = status.get("allocatable") or {}
    return parse_quantity(alloc.get("cpu")), parse_quantity(alloc.get("memory"))


def _capacity(status: dict) -> Tuple[float, float]:
    cap = status.get("capacity") or {}
    return parse_quantity(cap.get("cpu")), parse_quantity(cap.get("memory"))


def _metrics_index(metrics_body: Optional[dict]) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for item in (metrics_body or {}).get("items") or []:
        name = ((item.get("metadata") or {}).get("name") or "").strip()
        if name:
            index[name] = item
    return index


def _pod_app_name(pod: dict) -> str:
    labels = (pod.get("metadata") or {}).get("labels") or {}
    for key in ("app", "app.kubernetes.io/name", "k8s-app"):
        if labels.get(key):
            return str(labels[key])
    return (pod.get("metadata") or {}).get("name") or "unknown"


def _pod_phase(pod: dict) -> str:
    status = pod.get("status") or {}
    phase = status.get("phase") or "Unknown"
    for cs in status.get("containerStatuses") or []:
        waiting = (cs.get("state") or {}).get("waiting") or {}
        reason = waiting.get("reason")
        if reason:
            return reason
    return phase


def assemble_inventory(
    nodes_body: Optional[dict],
    metrics_body: Optional[dict],
    pods_body: Optional[dict],
) -> Dict[str, Any]:
    """Pure function: build fleet payload from K8s JSON (testable without cluster)."""
    metrics = _metrics_index(metrics_body)
    pods_by_node: Dict[str, List[dict]] = {}
    for pod in (pods_body or {}).get("items") or []:
        spec = pod.get("spec") or {}
        node_name = spec.get("nodeName") or ""
        meta = pod.get("metadata") or {}
        ns = meta.get("namespace") or ""
        if ns in ("kube-system",) and (meta.get("name") or "").startswith("helm-install"):
            continue
        entry = {
            "name": meta.get("name"),
            "namespace": ns,
            "app": _pod_app_name(pod),
            "phase": _pod_phase(pod),
            "ready": _pod_ready(pod),
        }
        pods_by_node.setdefault(node_name or "_unscheduled", []).append(entry)

    nodes: List[dict] = []
    for item in (nodes_body or {}).get("items") or []:
        meta = item.get("metadata") or {}
        status = item.get("status") or {}
        name = meta.get("name") or "unknown"
        cond = _condition_map(status.get("conditions") or [])
        cpu_alloc, mem_alloc = _allocatable(status)
        cpu_cap, mem_cap = _capacity(status)
        usage = ((metrics.get(name) or {}).get("usage") or {})
        cpu_used = parse_quantity(usage.get("cpu"))
        mem_used = parse_quantity(usage.get("memory"))
        addresses = {a.get("type"): a.get("address") for a in (status.get("addresses") or [])}
        info = status.get("nodeInfo") or {}
        roles = [
            label.replace("node-role.kubernetes.io/", "")
            for label in (meta.get("labels") or {})
            if label.startswith("node-role.kubernetes.io/")
        ]
        cpu_pct = round(100.0 * cpu_used / cpu_alloc, 1) if cpu_alloc else None
        mem_pct = round(100.0 * mem_used / mem_alloc, 1) if mem_alloc else None
        ready = cond.get("Ready") == "True"
        nodes.append({
            "name": name,
            "ready": ready,
            "roles": roles or ["worker"],
            "internal_ip": addresses.get("InternalIP"),
            "os": info.get("osImage"),
            "kernel": info.get("kernelVersion"),
            "kubelet": info.get("kubeletVersion"),
            "cpu": {
                "allocatable": cpu_alloc,
                "capacity": cpu_cap,
                "used": cpu_used,
                "percent": cpu_pct,
            },
            "memory": {
                "allocatable_bytes": mem_alloc,
                "capacity_bytes": mem_cap,
                "used_bytes": mem_used,
                "percent": mem_pct,
            },
            "pressure": {
                "memory": cond.get("MemoryPressure") == "True",
                "disk": cond.get("DiskPressure") == "True",
                "pid": cond.get("PIDPressure") == "True",
            },
            "battery": None,
            "pods": pods_by_node.get(name, []),
            "pod_count": len(pods_by_node.get(name, [])),
        })

    pending = pods_by_node.get("_unscheduled") or []
    return {
        "in_cluster": True,
        "node_count": len(nodes),
        "nodes": nodes,
        "unscheduled_pods": pending,
        "metrics_available": bool(metrics),
    }


def _pod_ready(pod: dict) -> bool:
    for cond in (pod.get("status") or {}).get("conditions") or []:
        if cond.get("type") == "Ready":
            return str(cond.get("status")) == "True"
    return False


async def fetch_cluster_inventory() -> Dict[str, Any]:
    if not in_cluster():
        return {
            "in_cluster": False,
            "node_count": 0,
            "nodes": [],
            "unscheduled_pods": [],
            "metrics_available": False,
            "message": "API is not running inside the cluster; node inventory unavailable.",
        }

    nodes_code, nodes_body = await k8s_get("/api/v1/nodes")
    if nodes_code == 403:
        return {
            "in_cluster": True,
            "node_count": 0,
            "nodes": [],
            "unscheduled_pods": [],
            "metrics_available": False,
            "error": "Forbidden listing nodes. Grant ClusterRole get/list on nodes.",
        }
    if nodes_code != 200:
        logger.warning("cluster inventory nodes HTTP %s", nodes_code)
        return {
            "in_cluster": True,
            "node_count": 0,
            "nodes": [],
            "unscheduled_pods": [],
            "metrics_available": False,
            "error": f"Failed to list nodes (HTTP {nodes_code})",
        }

    metrics_code, metrics_body = await k8s_get("/apis/metrics.k8s.io/v1beta1/nodes")
    if metrics_code != 200:
        logger.info("node metrics unavailable HTTP %s", metrics_code)
        metrics_body = {"items": []}

    pods_code, pods_body = await k8s_get("/api/v1/pods")
    if pods_code != 200:
        logger.warning("cluster inventory pods HTTP %s", pods_code)
        pods_body = {"items": []}

    payload = assemble_inventory(nodes_body, metrics_body, pods_body)
    payload["in_cluster"] = True
    return payload
