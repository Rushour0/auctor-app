"""Read + stream router for the Conversations page.

One fleet run == one conversation. This router is a thin async read layer over the raw
``fleet_runs`` / ``fleet_events`` collections (via ``request.app.state.db``, motor), mirroring the
shape of ``routers/x_oauth.py`` / ``routers/posts.py``. It never touches the sync ``WorkflowStore``:
writes stay with the workflow layer, reads stay here. Each raw event doc is mapped onto the docs/08
message contract by :func:`service.app.conversations.summarize_event` before it leaves the service.

Endpoints:

* ``GET  /api/conversations``               — one summary row per fleet run (newest first).
* ``GET  /api/conversations/{fleet_id}``     — full fleet doc + ordered message list.
* ``GET  /api/conversations/{fleet_id}/events`` — Server-Sent Events poll stream of new messages.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pymongo import ASCENDING, DESCENDING

from ..conversations import _iso, summarize_event, to_sse

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

# SSE poll cadence and hard cap on one stream's lifetime, in seconds. The stream self-terminates at
# ``_MAX_SECONDS`` so a client that never disconnects can't pin a worker forever; the browser's
# EventSource simply reconnects (replaying its ``last-event-id`` cursor) to keep following along.
_POLL_INTERVAL = 1.0
_MAX_SECONDS = 300


def _parse_cursor(after: str | datetime | None) -> datetime | None:
    """Parse an ISO-8601 cursor into a timezone-aware datetime; ``None`` for absent/unparseable.

    Accepts a datetime pass-through, tolerates a trailing ``Z`` (UTC), and coerces naive values to
    UTC so every comparison against ``recorded_at`` (stored tz-aware by ``WorkflowStore``) is safe.
    """
    if after is None:
        return None
    if isinstance(after, datetime):
        dt = after
    else:
        text = after.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _fetch_since(
    db, fleet_id: str, after_dt: datetime | None, limit: int = 200
) -> list[dict]:
    """Return this fleet's events after ``after_dt`` (all of them when ``None``), oldest-first.

    Factored out of the SSE generator so the query is directly unit-testable with a fake collection.
    """
    query: dict = {"fleet_id": fleet_id}
    if after_dt is not None:
        query["recorded_at"] = {"$gt": after_dt}
    cursor = db.fleet_events.find(query, {"_id": 0}).sort("recorded_at", ASCENDING)
    return await cursor.to_list(length=limit)


@router.get("")
async def list_conversations(
    request: Request,
    workspace_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List fleet runs newest-first, one summary row each, optionally scoped to a workspace."""
    db = request.app.state.db
    query: dict = {}
    if workspace_id is not None:
        query["workspace_id"] = workspace_id

    fleets = (
        await db.fleet_runs.find(query, {"_id": 0})
        .sort("updated_at", DESCENDING)
        .to_list(length=limit)
    )

    conversations: list[dict] = []
    for fleet in fleets:
        fleet_id = fleet.get("fleet_id")
        message_count = await db.fleet_events.count_documents({"fleet_id": fleet_id})
        latest = (
            await db.fleet_events.find({"fleet_id": fleet_id}, {"_id": 0})
            .sort("recorded_at", DESCENDING)
            .to_list(length=1)
        )
        conversations.append(
            {
                "fleet_id": fleet_id,
                "workspace_id": fleet.get("workspace_id"),
                "status": fleet.get("status"),
                "request": fleet.get("request"),
                "created_at": _iso(fleet.get("created_at")),
                "updated_at": _iso(fleet.get("updated_at")),
                "message_count": message_count,
                "last_message": summarize_event(latest[0]) if latest else None,
            }
        )

    return {"conversations": conversations}


@router.get("/{fleet_id}")
async def get_conversation(request: Request, fleet_id: str) -> dict:
    """Return one fleet run plus its full, oldest-first list of contract messages."""
    db = request.app.state.db
    fleet = await db.fleet_runs.find_one({"fleet_id": fleet_id}, {"_id": 0})
    if fleet is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    events = (
        await db.fleet_events.find({"fleet_id": fleet_id}, {"_id": 0})
        .sort("recorded_at", ASCENDING)
        .to_list(length=500)
    )
    messages = [summarize_event(event) for event in events]
    return {"fleet": fleet, "messages": messages, "message_count": len(messages)}


async def _event_stream(
    request: Request,
    db,
    fleet_id: str,
    after: str | None,
    poll_interval: float = _POLL_INTERVAL,
    max_seconds: float = _MAX_SECONDS,
):
    """Yield SSE frames for messages recorded after ``after``, polling until timeout/disconnect."""
    cursor = _parse_cursor(after)
    loop = asyncio.get_event_loop()
    started = loop.time()

    while True:
        docs = await _fetch_since(db, fleet_id, cursor)
        if docs:
            for doc in docs:
                yield to_sse(summarize_event(doc))
                recorded_at = doc.get("recorded_at")
                advanced = _parse_cursor(recorded_at)
                if advanced is not None:
                    cursor = advanced
        else:
            yield ": keepalive\n\n"

        if await request.is_disconnected():
            break
        if loop.time() - started > max_seconds:
            break
        await asyncio.sleep(poll_interval)


@router.get("/{fleet_id}/events")
async def stream_conversation_events(
    request: Request,
    fleet_id: str,
    after: str | None = Query(None),
) -> StreamingResponse:
    """Stream new messages for a fleet over SSE (long-poll), resuming from an ISO cursor.

    The cursor comes from ``after`` or, failing that, the standard ``Last-Event-ID`` reconnect
    header so a dropped EventSource resumes exactly where it left off.
    """
    db = request.app.state.db
    fleet = await db.fleet_runs.find_one({"fleet_id": fleet_id}, {"_id": 0})
    if fleet is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    cursor = after or request.headers.get("last-event-id")

    return StreamingResponse(
        _event_stream(request, db, fleet_id, cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
