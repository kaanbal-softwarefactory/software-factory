"""LanPublisherService — detect cluster LAN IP and report LAN endpoints.

GitOps materializes Service type=LoadBalancer (K3s ServiceLB). This publisher
only discovers the node/LAN IP for connection surfaces and health checks.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
from typing import Optional

from .types import PublisherResult

logger = logging.getLogger(__name__)


def detect_cluster_lan_ip(explicit: str = "") -> str:
    """Resolve LAN IP used to reach the K3s node from the local network.

    Priority:
      1. explicit argument / KAANBAL_CLUSTER_LAN_IP / CLUSTER_LAN_IP
      2. kubectl node InternalIP
      3. default route source address
    """
    for candidate in (
        (explicit or "").strip(),
        (os.environ.get("KAANBAL_CLUSTER_LAN_IP") or "").strip(),
        (os.environ.get("CLUSTER_LAN_IP") or "").strip(),
    ):
        if candidate:
            return candidate

    try:
        result = subprocess.run(
            [
                "kubectl", "get", "nodes",
                "-o", "jsonpath={.items[0].status.addresses[?(@.type==\"InternalIP\")].address}",
            ],
            capture_output=True, text=True, timeout=8,
        )
        ip = (result.stdout or "").strip()
        if ip and not ip.startswith("10.42.") and not ip.startswith("10.43."):
            return ip
        if ip:
            return ip
    except Exception as e:
        logger.debug("kubectl LAN IP probe failed: %s", e)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception as e:
        logger.debug("socket LAN IP probe failed: %s", e)

    return ""


class LanPublisherService:
    async def publish(
        self,
        *,
        app_name: str,
        env: str,
        node_port: Optional[int] = None,
        lan_ip: str = "",
        ensure: bool = True,
        ports: Optional[list] = None,
    ) -> PublisherResult:
        if not ensure:
            return PublisherResult(
                name="lan", ok=True, status="skipped", detail="LAN not requested"
            )

        ip = detect_cluster_lan_ip(lan_ip)
        if not ip:
            return PublisherResult(
                name="lan", ok=False, status="pending",
                detail="Could not detect cluster LAN IP — set KAANBAL_CLUSTER_LAN_IP",
            )

        urls = []
        meta_ports = ports or ([node_port] if node_port else [])
        for p in meta_ports:
            if p:
                urls.append(f"{ip}:{p}")
        if not urls:
            urls = [ip]

        return PublisherResult(
            name="lan", ok=True, status="ok",
            detail=f"LAN endpoint for {app_name}/{env} at {ip}",
            urls=urls,
            meta={"lan_ip": ip, "ports": list(meta_ports)},
        )
