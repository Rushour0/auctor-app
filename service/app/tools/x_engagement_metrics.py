"""Implements the ``x_engagement_metrics`` tool per
``.agent/tools/manifests/x_engagement_metrics.json``.

Read-only pull of a published tweet's ``public_metrics`` via X API v2
``GET /2/tweets/:id?tweet.fields=public_metrics``, using the client's stored OAuth user-context
access token (refreshed first if expired). Fails loud on a missing API key or an invalid
``platform_post_id`` rather than fabricating a metrics snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import x_integration


async def run(db: AsyncIOMotorDatabase, payload: dict[str, Any]) -> dict[str, Any]:
    client_id = payload["client_id"]
    draft_id = payload["draft_id"]
    platform_post_id = payload["platform_post_id"]

    out: dict[str, Any] = {"client_id": client_id, "draft_id": draft_id, "platform": "x"}

    try:
        access_token = await x_integration.get_valid_access_token(db, client_id)
        metrics = await x_integration.get_tweet_public_metrics(access_token, platform_post_id)
    except x_integration.XApiError as exc:
        out["status"] = "failed"
        out["error_message"] = f"{exc.kind}: {exc.message}"
        return out

    out["status"] = "success"
    out["impressions"] = metrics.get("impression_count", 0)
    out["likes"] = metrics.get("like_count", 0)
    out["reposts"] = metrics.get("retweet_count", 0)
    out["replies"] = metrics.get("reply_count", 0)
    out["bookmarks"] = metrics.get("bookmark_count", 0)
    out["captured_at"] = datetime.now(timezone.utc).isoformat()
    out["usage"] = {"cost_usd": 0.0}
    return out
