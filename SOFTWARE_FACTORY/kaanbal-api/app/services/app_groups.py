"""System inventory over existing app_group labels; ownership is metadata, not ACL."""
from __future__ import annotations

import re


def valid_slug(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_][a-z0-9_-]{0,99}", value))


def inventory(apps: list[dict], metadata: list[dict], owner: str | None = None) -> list[dict]:
    groups = {
        item["_id"]: {"slug": item["_id"], "name": item.get("name") or item["_id"],
                      "description": item.get("description", ""), "owner": item.get("owner"),
                      "stage": item.get("stage", "active"), "apps": []}
        for item in metadata
    }
    for app in apps:
        slug = str(app.get("app_group") or "").strip().lower()
        key = slug or ""
        group = groups.setdefault(key, {"slug": slug, "name": slug or "Sin grupo",
                                       "description": "", "owner": None, "stage": "active", "apps": []})
        group["apps"].append({"name": app["name"], "template": app.get("template"),
                              "status": app.get("status", "unknown"),
                              "environments": app.get("environments") or []})
    result = []
    for group in groups.values():
        if owner is not None and (group["owner"] or "") != owner:
            continue
        group["apps"].sort(key=lambda a: a["name"])
        group["app_count"] = len(group["apps"])
        result.append(group)
    return sorted(result, key=lambda g: (not bool(g["slug"]), g["name"].lower()))
