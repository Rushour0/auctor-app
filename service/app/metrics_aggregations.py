"""Per-block Mongo aggregations for the Metrics page and the scheduler push.

Each function is a pure sync-pymongo helper taking ``(db, workspace_id[, platform])``
and returning a plain ``dict``/``list`` — no raw Mongo lives in the router. Pulling
the pipelines out here keeps the endpoint readable, makes each aggregation
independently testable, and — most importantly — lets ``build_metrics_payload`` be
imported by BOTH the ``GET /metrics`` router and the scheduler push so the exported
payload and the pushed payload are byte-identical.

``_match`` is the single fleet-isolation scope point: every collection read is scoped
to a ``workspace_id`` through it. COGS is surfaced even on failed/cancelled pipelines
(fabri emits the usage event at the end of the loop regardless of outcome, so a failed
pipeline still carries its burned cost) — failed spend is never dropped from the total.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import DESCENDING
from pymongo.database import Database

from service.auctor.workflow import utc_now


USD_TO_INR = 83.0


def available_platforms() -> list[str]:
    """The fixed per-platform contract. x/linkedin are surfaced independently,
    never collapsed into a single boolean."""
    return ["x", "linkedin"]


def _match(workspace_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The single fleet-isolation scope point — merge the workspace scope with
    any extra query terms."""
    query: dict[str, Any] = {"workspace_id": workspace_id}
    if extra:
        query.update(extra)
    return query


def counts(db: Database, workspace_id: str) -> dict[str, int]:
    """Top-line document counts across the workflow collections (mirrors the
    count blocks in ``WorkflowStore.status``)."""
    scope = _match(workspace_id)
    return {
        "fleets": db.fleet_runs.count_documents(scope),
        "pipelines": db.client_pipelines.count_documents(scope),
        "posts": db.content_posts.count_documents(scope),
        "events": db.fleet_events.count_documents(scope),
        "triggers": db.workflow_triggers.count_documents(scope),
    }


def posts_by_status(
    db: Database, workspace_id: str, platform: str | None = None
) -> dict[str, int]:
    """Content posts grouped by ``status``. When ``platform`` is set the drill-down
    is per-platform — it keys off ``platform_status.<platform>`` existing, never a
    boolean flag — so the x/linkedin tabs count independently."""
    extra: dict[str, Any] = {}
    if platform:
        extra[f"platform_status.{platform}"] = {"$exists": True}
    pipeline = [
        {"$match": _match(workspace_id, extra or None)},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    out: dict[str, int] = {}
    for row in db.content_posts.aggregate(pipeline):
        if row.get("_id") is not None:
            out[str(row["_id"])] = int(row.get("count", 0))
    return out


def cost_rollup(db: Database, workspace_id: str) -> dict[str, Any]:
    """Roll up pipeline COGS in Python so failed/cancelled spend stays surfaced.

    ``avg_per_run_usd`` divides total spend by the pipeline count; ``avg_per_post_usd``
    divides by the number of published posts. ``by_status_usd`` groups spend by pipeline
    status and ``failed_usd`` sums the failed + cancelled buckets.
    """
    total_usd = 0.0
    pipeline_count = 0
    priced_pipelines = 0
    by_status_usd: dict[str, float] = {}
    for doc in db.client_pipelines.find(
        _match(workspace_id),
        {"_id": 0, "usage": 1, "status": 1, "pipeline": 1, "client_id": 1},
    ):
        pipeline_count += 1
        cost = float((doc.get("usage") or {}).get("cost_usd", 0.0) or 0.0)
        total_usd += cost
        if cost > 0:
            priced_pipelines += 1
        status = str(doc.get("status") or "unknown")
        by_status_usd[status] = by_status_usd.get(status, 0.0) + cost

    published_posts = db.content_posts.count_documents(
        _match(workspace_id, {"status": "published"})
    )
    failed_usd = by_status_usd.get("failed", 0.0) + by_status_usd.get("cancelled", 0.0)
    return {
        "total_usd": round(total_usd, 6),
        "pipeline_count": pipeline_count,
        "priced_pipelines": priced_pipelines,
        "published_posts": published_posts,
        "avg_per_run_usd": round(total_usd / max(1, pipeline_count), 6),
        "avg_per_post_usd": round(total_usd / max(1, published_posts), 6),
        "by_status_usd": {k: round(v, 6) for k, v in by_status_usd.items()},
        "failed_usd": round(failed_usd, 6),
        "usd_to_inr": USD_TO_INR,
    }


def cost_by_provider(db: Database, workspace_id: str) -> list[dict[str, Any]]:
    """Provider-level spend from fleet events that carry a ``payload.cost_usd``."""
    pipeline = [
        {"$match": _match(workspace_id, {"payload.cost_usd": {"$exists": True}})},
        {
            "$group": {
                "_id": "$payload.provider",
                "cost_usd": {"$sum": "$payload.cost_usd"},
                "events": {"$sum": 1},
            }
        },
        {"$sort": {"cost_usd": -1}},
    ]
    out: list[dict[str, Any]] = []
    for row in db.fleet_events.aggregate(pipeline):
        out.append(
            {
                "provider": row.get("_id") or "unknown",
                "cost_usd": round(float(row.get("cost_usd", 0.0) or 0.0), 6),
                "events": int(row.get("events", 0)),
            }
        )
    return out


def top_pipelines(db: Database, workspace_id: str) -> list[dict[str, Any]]:
    """The five most expensive pipelines by accumulated ``usage.cost_usd``."""
    cursor = (
        db.client_pipelines.find(
            _match(workspace_id),
            {"_id": 0, "client_id": 1, "pipeline": 1, "status": 1, "usage": 1},
        )
        .sort("usage.cost_usd", DESCENDING)
        .limit(5)
    )
    out: list[dict[str, Any]] = []
    for doc in cursor:
        cost = float((doc.get("usage") or {}).get("cost_usd", 0.0) or 0.0)
        out.append(
            {
                "client_id": doc.get("client_id"),
                "pipeline": doc.get("pipeline"),
                "status": doc.get("status"),
                "cost_usd": round(cost, 6),
            }
        )
    return out


def posts_per_day(
    db: Database, workspace_id: str, start: datetime
) -> list[dict[str, Any]]:
    """Post volume over a densified 7-day window starting at ``start`` (UTC).

    Days with no posts still appear as zero-count buckets so the chart never has
    gaps."""
    pipeline = [
        {"$match": _match(workspace_id, {"created_at": {"$gte": start}})},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$created_at",
                        "timezone": "UTC",
                    }
                },
                "count": {"$sum": 1},
            }
        },
    ]
    daily: dict[str, int] = {}
    for row in db.content_posts.aggregate(pipeline):
        daily[str(row["_id"])] = int(row.get("count", 0))
    out: list[dict[str, Any]] = []
    for i in range(7):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        out.append({"day": day, "count": daily.get(day, 0)})
    return out


def failure_reasons(db: Database, workspace_id: str) -> list[dict[str, Any]]:
    """The top five failure reasons across fleet events that failed or carry an error."""
    pipeline = [
        {
            "$match": _match(
                workspace_id,
                {
                    "$or": [
                        {"payload.status": {"$in": ["failed"]}},
                        {"payload.error": {"$exists": True}},
                    ]
                },
            )
        },
        {"$group": {"_id": "$payload.error", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    out: list[dict[str, Any]] = []
    for row in db.fleet_events.aggregate(pipeline):
        out.append(
            {
                "reason": row.get("_id") or "unknown",
                "count": int(row.get("count", 0)),
            }
        )
    return out


def recent_events(
    db: Database, workspace_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    """The most recent fleet events for the activity feed."""
    return list(
        db.fleet_events.find(_match(workspace_id), {"_id": 0})
        .sort("recorded_at", DESCENDING)
        .limit(limit)
    )


def build_metrics_payload(
    db: Database, workspace_id: str, platform: str | None = None
) -> dict[str, Any]:
    """Assemble the one flat metrics payload used by BOTH the router and the
    scheduler push, so the exported and pushed payloads are byte-identical.

    ``platform`` optionally scopes ``posts_by_status`` to a single platform tab.
    The 7-day window starts six days before today, floored to midnight UTC.
    """
    now = utc_now()
    start = (now - timedelta(days=6)).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )
    return {
        "workspace_id": workspace_id,
        "platform": platform,
        "available_platforms": available_platforms(),
        "generated_at": now.isoformat(),
        "counts": counts(db, workspace_id),
        "posts_by_status": posts_by_status(db, workspace_id, platform),
        "cost": cost_rollup(db, workspace_id),
        "cost_by_provider": cost_by_provider(db, workspace_id),
        "top_pipelines": top_pipelines(db, workspace_id),
        "posts_per_day": posts_per_day(db, workspace_id, start),
        "failure_reasons": failure_reasons(db, workspace_id),
        "recent_events": recent_events(db, workspace_id),
    }
