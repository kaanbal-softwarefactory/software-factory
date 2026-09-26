"""
Activity Log Service
====================
Robust activity logging system that stores all platform events in MongoDB.
Captures: API requests, deployments, errors, user actions, system events.

Collections:
  - activity_logs: All activity events (TTL indexed for auto-cleanup)

Usage:
  from app.services.activity_log import activity_log

  # Log an action
  await activity_log.log("app.deploy.started", actor="admin", target="my-app",
                         detail={"environments": ["dev","prod"]})

  # Log an error
  await activity_log.error("app.deploy.failed", actor="admin", target="my-app",
                           detail={"error": "git clone failed"})
"""

import logging
import traceback
import asyncio
import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import httpx

from app.db import get_db
from app.defaults import LOG_RETENTION_DAYS, LOG_FORWARDING_TIMEOUT_SEC, LOG_FORWARDING_MIN_LEVEL

logger = logging.getLogger(__name__)

# Log categories for filtering
CATEGORY_API = "api"
CATEGORY_DEPLOY = "deploy"
CATEGORY_AUTH = "auth"
CATEGORY_SYSTEM = "system"
CATEGORY_APP = "app"
CATEGORY_TEMPLATE = "template"
CATEGORY_CONFIG = "config"
CATEGORY_ERROR = "error"

# Log levels
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"
LEVEL_DEBUG = "debug"

_LEVEL_ORDER = {
    LEVEL_DEBUG: 10,
    LEVEL_INFO: 20,
    LEVEL_WARN: 30,
    LEVEL_ERROR: 40,
}


class ActivityLogService:
    """Singleton-style service for writing activity logs to MongoDB."""

    COLLECTION = "activity_logs"

    def __init__(self):
        self._config_cache: Dict[str, Any] = {
            "loaded_at": None,
            "retention_days": LOG_RETENTION_DAYS,
            "forwarding_webhook_url": "",
            "forwarding_min_level": LOG_FORWARDING_MIN_LEVEL,
            "forwarding_timeout_sec": LOG_FORWARDING_TIMEOUT_SEC,
        }

    async def _load_runtime_config(self, force: bool = False) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        loaded_at = self._config_cache.get("loaded_at")
        if not force and loaded_at and (now - loaded_at).total_seconds() < 60:
            return self._config_cache

        db = get_db()
        if db is None:
            self._config_cache["loaded_at"] = now
            return self._config_cache

        try:
            cfg = await db.system_config.find_one({"_id": "main"}, {
                "logs_retention_days": 1,
                "logs_forwarding_webhook_url": 1,
                "logs_forwarding_min_level": 1,
            })
            self._config_cache = {
                "loaded_at": now,
                "retention_days": int((cfg or {}).get("logs_retention_days", LOG_RETENTION_DAYS) or LOG_RETENTION_DAYS),
                "forwarding_webhook_url": str((cfg or {}).get("logs_forwarding_webhook_url", "") or "").strip(),
                "forwarding_min_level": str((cfg or {}).get("logs_forwarding_min_level", LOG_FORWARDING_MIN_LEVEL) or LOG_FORWARDING_MIN_LEVEL).lower(),
                "forwarding_timeout_sec": LOG_FORWARDING_TIMEOUT_SEC,
            }
        except Exception as e:
            logger.warning(f"activity_log config load failed: {e}")
            self._config_cache["loaded_at"] = now

        return self._config_cache

    @staticmethod
    def _sanitize(data: Any) -> Any:
        if isinstance(data, dict):
            cleaned = {}
            for k, v in data.items():
                key = str(k).lower()
                if any(s in key for s in ["token", "password", "secret", "authorization", "api_key", "apikey"]):
                    cleaned[k] = "***"
                else:
                    cleaned[k] = ActivityLogService._sanitize(v)
            return cleaned
        if isinstance(data, list):
            return [ActivityLogService._sanitize(v) for v in data]
        if isinstance(data, str):
            s = data
            if "bearer " in s.lower():
                return "***"
            if "@" in s and "http" in s and ":" in s:
                return s.replace(s, "***") if "token" in s.lower() else s
            return s
        return data

    async def _ensure_indexes(self):
        """Create indexes on first use. Idempotent."""
        db = get_db()
        if db is None:
            return
        col = db[self.COLLECTION]
        cfg = await self._load_runtime_config(force=True)
        retention_days = max(1, int(cfg.get("retention_days", LOG_RETENTION_DAYS)))
        ttl_seconds = retention_days * 86400

        idx_info = await col.index_information()
        ttl_idx_name = "activity_ttl_idx"
        existing_ttl = idx_info.get(ttl_idx_name)
        if existing_ttl:
            current_expire = existing_ttl.get("expireAfterSeconds")
            if current_expire != ttl_seconds:
                await col.drop_index(ttl_idx_name)

        await col.create_index("timestamp", expireAfterSeconds=ttl_seconds, name=ttl_idx_name)
        await col.create_index("category")
        await col.create_index("action")
        await col.create_index("actor")
        await col.create_index("target")
        await col.create_index("level")
        await col.create_index([("timestamp", -1)])

    async def init(self):
        """Called once at startup to ensure indexes exist."""
        try:
            await self._ensure_indexes()
        except Exception as e:
            logger.warning(f"activity_log index creation deferred: {e}")

    async def log(
        self,
        action: str,
        *,
        category: str = CATEGORY_SYSTEM,
        level: str = LEVEL_INFO,
        actor: Optional[str] = None,
        target: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        method: Optional[str] = None,
        path: Optional[str] = None,
        status_code: Optional[int] = None,
        duration_ms: Optional[float] = None,
        ip: Optional[str] = None,
    ):
        """Write a single activity log entry."""
        db = get_db()
        if db is None:
            return

        doc = {
            "action": action,
            "category": category,
            "level": level,
            "actor": actor,
            "target": target,
            "detail": self._sanitize(detail or {}),
            "request_id": request_id,
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "ip": ip,
            "timestamp": datetime.now(timezone.utc),
        }
        detail_json = ""
        try:
            detail_json = json.dumps(doc["detail"], ensure_ascii=False)
        except Exception:
            detail_json = str(doc["detail"])
        doc["detail_text"] = detail_json[:4000]
        try:
            await db[self.COLLECTION].insert_one(doc)
            cfg = await self._load_runtime_config(force=False)
            asyncio.create_task(self._forward_if_needed(doc, cfg))
        except Exception as e:
            # Never let logging failures break the application
            logger.warning(f"activity_log write failed: {e}")

    async def _forward_if_needed(self, doc: Dict[str, Any], cfg: Dict[str, Any]):
        url = str(cfg.get("forwarding_webhook_url") or "").strip()
        if not url:
            return

        min_level = str(cfg.get("forwarding_min_level") or LOG_FORWARDING_MIN_LEVEL).lower()
        if _LEVEL_ORDER.get(str(doc.get("level") or "info").lower(), 20) < _LEVEL_ORDER.get(min_level, 40):
            return

        payload = {
            "action": doc.get("action"),
            "category": doc.get("category"),
            "level": doc.get("level"),
            "actor": doc.get("actor"),
            "target": doc.get("target"),
            "timestamp": doc.get("timestamp").isoformat() if isinstance(doc.get("timestamp"), datetime) else doc.get("timestamp"),
            "request_id": doc.get("request_id"),
            "method": doc.get("method"),
            "path": doc.get("path"),
            "status_code": doc.get("status_code"),
            "duration_ms": doc.get("duration_ms"),
            "detail": doc.get("detail"),
        }

        timeout_sec = int(cfg.get("forwarding_timeout_sec", LOG_FORWARDING_TIMEOUT_SEC))
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                await client.post(url, json=payload)
        except Exception as e:
            logger.warning(f"activity_log forwarding failed: {e}")

    async def error(
        self,
        action: str,
        *,
        category: str = CATEGORY_ERROR,
        actor: Optional[str] = None,
        target: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        exc: Optional[Exception] = None,
        **kwargs,
    ):
        """Convenience: log an error-level event with optional exception info."""
        detail = detail or {}
        if exc:
            detail["exception"] = str(exc)
            detail["traceback"] = traceback.format_exception(type(exc), exc, exc.__traceback__)[-3:]
        await self.log(action, category=category, level=LEVEL_ERROR,
                       actor=actor, target=target, detail=detail, **kwargs)

    async def query(
        self,
        *,
        category: Optional[str] = None,
        level: Optional[str] = None,
        actor: Optional[str] = None,
        target: Optional[str] = None,
        action: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Query logs with filters. Returns {logs: [...], total: N}."""
        db = get_db()
        if db is None:
            return {"logs": [], "total": 0}

        query_filter: Dict[str, Any] = {}
        if category:
            query_filter["category"] = category
        if level:
            query_filter["level"] = level
        if actor:
            query_filter["actor"] = actor
        if target:
            query_filter["target"] = target
        if action:
            query_filter["action"] = {"$regex": action, "$options": "i"}
        if search:
            query_filter["$or"] = [
                {"action": {"$regex": search, "$options": "i"}},
                {"target": {"$regex": search, "$options": "i"}},
                {"actor": {"$regex": search, "$options": "i"}},
                {"detail_text": {"$regex": search, "$options": "i"}},
            ]
        if since or until:
            ts_filter = {}
            if since:
                ts_filter["$gte"] = since
            if until:
                ts_filter["$lte"] = until
            query_filter["timestamp"] = ts_filter

        col = db[self.COLLECTION]
        total = await col.count_documents(query_filter)
        cursor = col.find(query_filter).sort("timestamp", -1).skip(skip).limit(limit)
        logs = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            logs.append(doc)

        return {"logs": logs, "total": total}

    async def get_stats(self) -> Dict[str, Any]:
        """Aggregate stats: counts by category, level, top actors, recent errors."""
        db = get_db()
        if db is None:
            return {}

        col = db[self.COLLECTION]

        by_category = await col.aggregate([
            {"$group": {"_id": "$category", "count": {"$sum": 1}}}
        ]).to_list(50)

        by_level = await col.aggregate([
            {"$group": {"_id": "$level", "count": {"$sum": 1}}}
        ]).to_list(10)

        recent_errors = await col.find({"level": "error"}).sort("timestamp", -1).limit(10).to_list(10)
        for e in recent_errors:
            e["_id"] = str(e["_id"])

        total = await col.count_documents({})

        return {
            "total": total,
            "by_category": {r["_id"]: r["count"] for r in by_category if r["_id"]},
            "by_level": {r["_id"]: r["count"] for r in by_level if r["_id"]},
            "recent_errors": recent_errors,
        }

    async def get_grouped_stats(self) -> Dict[str, Any]:
        db = get_db()
        if db is None:
            return {"by_target": {}, "by_env": {}}

        col = db[self.COLLECTION]
        by_target_rows = await col.aggregate([
            {"$match": {"target": {"$nin": [None, "", "-"]}}},
            {"$group": {"_id": "$target", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ]).to_list(50)

        by_env_rows = await col.aggregate([
            {
                "$project": {
                    "env": {
                        "$ifNull": [
                            "$detail.event.env",
                            {
                                "$cond": [
                                    {"$eq": ["$method", None]},
                                    None,
                                    {
                                        "$cond": [
                                            {"$regexMatch": {"input": "$path", "regex": "/dev(/|$)"}},
                                            "dev",
                                            {
                                                "$cond": [
                                                    {"$regexMatch": {"input": "$path", "regex": "/staging(/|$)"}},
                                                    "staging",
                                                    {
                                                        "$cond": [
                                                            {"$regexMatch": {"input": "$path", "regex": "/prod(/|$)"}},
                                                            "prod",
                                                            "unknown",
                                                        ]
                                                    },
                                                ]
                                            },
                                        ]
                                    },
                                ]
                            },
                        ]
                    }
                }
            },
            {"$match": {"env": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$env", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]).to_list(20)

        return {
            "by_target": {r["_id"]: r["count"] for r in by_target_rows if r.get("_id")},
            "by_env": {r["_id"]: r["count"] for r in by_env_rows if r.get("_id")},
        }

    @staticmethod
    def to_csv(logs: List[Dict[str, Any]]) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "timestamp",
                "level",
                "category",
                "action",
                "actor",
                "target",
                "method",
                "path",
                "status_code",
                "duration_ms",
                "request_id",
                "ip",
                "detail_text",
            ],
        )
        writer.writeheader()
        for log in logs:
            writer.writerow({
                "timestamp": log.get("timestamp"),
                "level": log.get("level"),
                "category": log.get("category"),
                "action": log.get("action"),
                "actor": log.get("actor"),
                "target": log.get("target"),
                "method": log.get("method"),
                "path": log.get("path"),
                "status_code": log.get("status_code"),
                "duration_ms": log.get("duration_ms"),
                "request_id": log.get("request_id"),
                "ip": log.get("ip"),
                "detail_text": log.get("detail_text"),
            })
        return output.getvalue()


# Singleton
activity_log = ActivityLogService()
