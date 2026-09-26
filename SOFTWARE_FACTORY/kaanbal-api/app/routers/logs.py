from __future__ import annotations

from datetime import datetime
from typing import Optional
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.routers.auth import get_current_active_user
from app.services.activity_log import activity_log
from app.db import get_db


router = APIRouter(dependencies=[Depends(get_current_active_user)])


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {value}") from exc


@router.get("")
async def list_logs(
    category: Optional[str] = None,
    level: Optional[str] = None,
    actor: Optional[str] = None,
    target: Optional[str] = None,
    action: Optional[str] = None,
    search: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    skip: int = 0,
    limit: int = Query(default=100, ge=1, le=1000),
):
    return await activity_log.query(
        category=category,
        level=level,
        actor=actor,
        target=target,
        action=action,
        search=search,
        since=_parse_dt(since),
        until=_parse_dt(until),
        skip=skip,
        limit=limit,
    )


@router.get("/stats")
async def get_log_stats():
    return await activity_log.get_stats()


@router.get("/stats/grouped")
async def get_grouped_log_stats():
    return await activity_log.get_grouped_stats()


@router.post("/ingest")
async def ingest_log(payload: dict, current_user=Depends(get_current_active_user)):
    """
    Generic endpoint to ingest client-side or external integration logs.
    Expected fields (all optional):
      - action, category, level, target, detail, source, timestamp
    """
    action = str(payload.get("action") or "external.log")
    category = str(payload.get("category") or "system")
    level = str(payload.get("level") or "info")
    target = payload.get("target")
    detail = payload.get("detail") or {}
    source = payload.get("source")

    if source:
        detail["source"] = source

    await activity_log.log(
        action,
        category=category,
        level=level,
        actor=getattr(current_user, "username", "unknown"),
        target=target,
        detail=detail,
    )
    return {"status": "ok", "ingested": True}


@router.get("/export")
async def export_logs(
    category: Optional[str] = None,
    level: Optional[str] = None,
    actor: Optional[str] = None,
    target: Optional[str] = None,
    action: Optional[str] = None,
    search: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
):
    result = await activity_log.query(
        category=category,
        level=level,
        actor=actor,
        target=target,
        action=action,
        search=search,
        since=_parse_dt(since),
        until=_parse_dt(until),
        skip=0,
        limit=5000,
    )

    async def generate():
        for item in result["logs"]:
            yield json.dumps(item, default=str) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="activity-logs.ndjson"'},
    )


@router.get("/export.csv")
async def export_logs_csv(
    category: Optional[str] = None,
    level: Optional[str] = None,
    actor: Optional[str] = None,
    target: Optional[str] = None,
    action: Optional[str] = None,
    search: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
):
    result = await activity_log.query(
        category=category,
        level=level,
        actor=actor,
        target=target,
        action=action,
        search=search,
        since=_parse_dt(since),
        until=_parse_dt(until),
        skip=0,
        limit=5000,
    )
    csv_text = activity_log.to_csv(result["logs"])
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="activity-logs.csv"'},
    )


@router.delete("")
async def clear_logs(
    category: Optional[str] = None,
    level: Optional[str] = None,
    target: Optional[str] = None,
    older_than: Optional[str] = None,
):
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    delete_filter = {}
    if category:
        delete_filter["category"] = category
    if level:
        delete_filter["level"] = level
    if target:
        delete_filter["target"] = target
    if older_than:
        delete_filter["timestamp"] = {"$lt": _parse_dt(older_than)}

    if not delete_filter:
        raise HTTPException(status_code=400, detail="Refusing to delete all logs without a filter")

    result = await db[activity_log.COLLECTION].delete_many(delete_filter)
    return {"deleted": result.deleted_count, "filter": delete_filter}