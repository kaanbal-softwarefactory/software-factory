#!/usr/bin/env python3
"""Limpia devices Tailscale huérfanos del lab (tag:k8s / database / iot / operators viejos).

Regla: solo se conservan hostnames que el cluster declara HOY
(annotations tailscale.com/hostname en Service/Ingress) + el operador online.
El resto (remanentes de installs anteriores) se borra.

Uso:
  sudo python3 tools/cleanup-tailscale-orphans.py            # dry-run
  sudo python3 tools/cleanup-tailscale-orphans.py --apply    # borra de verdad
  sudo python3 tools/cleanup-tailscale-orphans.py --apply --env /etc/kaanbal/installer.env
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def parse_env(path: str) -> dict:
    cfg = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip().replace("\r", "")
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip().upper()] = v.strip().strip("'\"")
    return cfg


def http_json(url, headers=None, data=None, method=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode() or "{}"
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except Exception:
            body = {}
        return e.code, body


def oauth_token(cid: str, secret: str) -> str:
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    st, resp = http_json(
        "https://api.tailscale.com/api/v2/oauth/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic}",
        },
        data=data,
    )
    if st != 200:
        raise SystemExit(f"oauth failed HTTP {st}")
    return resp["access_token"]


def kubectl_json(args: list[str]):
    cmd = ["k3s", "kubectl", *args, "-o", "json"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
        return json.loads(out or "{}")
    except Exception:
        return {}


def cluster_keep_hostnames() -> set[str]:
    """Hostnames declared by live Services/Ingress annotations."""
    keep = set()
    for kind in ("svc", "ingress"):
        data = kubectl_json(["get", kind, "-A"])
        for item in data.get("items") or []:
            ann = (item.get("metadata") or {}).get("annotations") or {}
            host = (ann.get("tailscale.com/hostname") or "").strip().lower()
            if host:
                keep.add(host.split(".")[0])  # short name
                keep.add(host)
    # Always keep current operator identity short names
    keep.update({"tailscale-operator", "tailscale-operator-1"})
    return keep


def device_short(name: str) -> str:
    n = (name or "").lower().strip()
    return n.split(".")[0]


def is_lab_tagged(device: dict) -> bool:
    tags = device.get("tags") or []
    return any(t.startswith("tag:k8s") or t in ("tag:database", "tag:iot", "tag:k8s-operator")
               for t in tags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Delete orphans (default dry-run)")
    ap.add_argument("--env", default="/etc/kaanbal/installer.env")
    ap.add_argument("--delete-offline-operators", action="store_true", default=True,
                    help="Delete offline duplicate tailscale-operator* devices")
    ap.add_argument("--wipe-all-tagged", action="store_true",
                    help="Delete ALL tag:k8s/database/iot/k8s-operator devices (use before full lab wipe)")
    args = ap.parse_args()

    cfg = parse_env(args.env)
    cid = cfg.get("TAILSCALE_CLIENT_ID", "")
    secret = cfg.get("TAILSCALE_CLIENT_SECRET", "")
    if not cid or not secret:
        raise SystemExit("missing Tailscale OAuth in installer.env")

    token = oauth_token(cid, secret)
    st, resp = http_json(
        "https://api.tailscale.com/api/v2/tailnet/-/devices",
        headers={"Authorization": f"Bearer {token}"},
    )
    if st != 200:
        raise SystemExit(f"list devices HTTP {st}")
    devices = resp.get("devices") or []

    keep = set() if args.wipe_all_tagged else cluster_keep_hostnames()
    print("KEEP_FROM_CLUSTER:", ", ".join(sorted(keep)) or ("(none — wipe-all)" if args.wipe_all_tagged else "(none)"))

    orphans = []
    kept = []
    for d in devices:
        name = d.get("name") or d.get("hostname") or ""
        short = device_short(name)
        hostname = (d.get("hostname") or short).lower()
        tags = d.get("tags") or []
        online = d.get("online")
        if not is_lab_tagged(d):
            continue  # personal machines etc.
        # Keep if cluster declares this hostname
        if short in keep or hostname in keep or any(short == k or hostname.startswith(k) for k in keep):
            # Special: offline duplicate operators → orphan
            if args.delete_offline_operators and short.startswith("tailscale-operator") and online is False:
                orphans.append(d)
                continue
            kept.append(d)
            continue
        orphans.append(d)

    print(f"KEPT={len(kept)} ORPHANS={len(orphans)} mode={'APPLY' if args.apply else 'DRY-RUN'}")
    for d in kept:
        print("  KEEP", d.get("hostname") or d.get("name"), "online="+str(d.get("online")), d.get("tags"))
    for d in orphans:
        print("  ORPHAN", d.get("hostname") or d.get("name"), "online="+str(d.get("online")), d.get("tags"))

    if not args.apply:
        print("DRY_RUN_OK (pasa --apply para borrar)")
        return 0

    deleted, failed = [], []
    for d in orphans:
        did = d.get("id")
        name = d.get("hostname") or d.get("name")
        st, _ = http_json(
            f"https://api.tailscale.com/api/v2/device/{urllib.parse.quote(did)}",
            headers={"Authorization": f"Bearer {token}"},
            method="DELETE",
        )
        if st in (200, 204):
            deleted.append(name)
            print("  DELETED", name)
        else:
            failed.append((name, st))
            print("  FAIL", name, st)

    print(f"DONE deleted={len(deleted)} failed={len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
