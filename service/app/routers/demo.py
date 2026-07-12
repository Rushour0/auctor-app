"""POST /api/demo/suggest — the one deliberately unauthenticated route in this
service. Public, no-signup: give a LinkedIn URL or X handle, get back 3 real,
sourced post suggestions (see ../demo.py for the Linkup-research + Anthropic-draft
logic this route wraps).

Rate-limited per client IP via the ``demo_requests`` collection rather than an
in-memory counter, for the same reason the content-loop scheduler is Mongo-backed
(see ENGINEERING-WAVES.md Wave 2): a redeploy must not silently reset the limit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import demo
from ..config import settings

router = APIRouter(prefix="/api/demo", tags=["demo"])


class SuggestRequest(BaseModel):
    linkedin_url: str | None = Field(default=None, max_length=500)
    twitter_handle: str | None = Field(default=None, max_length=100)


def _client_ip(request: Request) -> str:
    # Trust X-Forwarded-For's first hop only when present (Coolify/Traefik sits in
    # front); fall back to the direct peer for local/dev requests.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _enforce_rate_limit(request: Request) -> None:
    db = request.app.state.db
    ip = _client_ip(request)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    count = await db.demo_requests.count_documents({"ip": ip, "requested_at": {"$gte": since}})
    if count >= settings.demo_rate_limit_per_day:
        raise HTTPException(
            status_code=429,
            detail=f"Limit of {settings.demo_rate_limit_per_day} lookups per day reached — try again tomorrow.",
        )
    await db.demo_requests.insert_one({"ip": ip, "requested_at": datetime.now(timezone.utc)})


_ERROR_STATUS = {
    "missing_handle": 400,
    "missing_api_key": 503,
    "search_failed": 502,
    "no_signal": 404,
    "suggest_failed": 502,
}


@router.post("/suggest")
async def suggest(payload: SuggestRequest, request: Request) -> dict:
    if not payload.linkedin_url and not payload.twitter_handle:
        raise HTTPException(
            status_code=400, detail="Provide a LinkedIn URL or an X/Twitter handle."
        )

    await _enforce_rate_limit(request)

    try:
        return await run_in_threadpool(
            demo.run_public_suggestion, payload.linkedin_url, payload.twitter_handle
        )
    except demo.DemoError as error:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(error.kind, 500), detail=error.message
        ) from error
