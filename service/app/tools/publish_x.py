"""Implements the ``publish_x`` tool per ``.agent/tools/manifests/publish_x.json``.

Publishes one client's approved post to X (Twitter) via X API v2 ``POST /2/tweets``, using that
client's stored OAuth user-context access token (refreshed first if expired). Enforces the
manifest's per-post, single-use ``approval_id`` contract and fails loud (never retries, never
fabricates a result) on a missing API key or a missing/already-used approval.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import x_integration


async def _consume_approval(
    db: AsyncIOMotorDatabase, client_id: str, approval_id: str
) -> str | None:
    """Atomically mark ``approval_id`` consumed for ``client_id``.

    Returns None on success, or an error_message string if the approval doesn't exist, isn't for
    this client, isn't approved, or was already used. Scoped by client_id — fleet isolation.
    """
    doc = await db.approval_requests.find_one_and_update(
        {"id": approval_id, "client_id": client_id, "status": "approved", "consumed_at": None},
        {"$set": {"consumed_at": datetime.now(timezone.utc)}},
    )
    if doc is not None:
        return None

    existing = await db.approval_requests.find_one({"id": approval_id, "client_id": client_id})
    if existing is None:
        return (
            f"missing_approval: no approval_id={approval_id!r} on file for client_id={client_id!r}."
        )
    if existing.get("status") != "approved":
        return f"missing_approval: approval_id={approval_id!r} is not approved (status={existing.get('status')!r})."
    return f"missing_approval: approval_id={approval_id!r} was already used for a prior publish."


async def run(db: AsyncIOMotorDatabase, payload: dict[str, Any]) -> dict[str, Any]:
    client_id = payload["client_id"]
    draft_id = payload["draft_id"]
    text = payload["text"]
    approval_id = payload["approval_id"]
    media_assets = payload.get("media_assets") or []

    out: dict[str, Any] = {"client_id": client_id, "draft_id": draft_id}

    approval_error = await _consume_approval(db, client_id, approval_id)
    if approval_error is not None:
        out["status"] = "failed"
        out["error_message"] = approval_error
        return out

    try:
        access_token = await x_integration.get_valid_access_token(db, client_id)

        # X requires media to be uploaded via a separate media endpoint before it can be
        # attached to a tweet by media_id; asset_url -> media_id upload is not yet wired up here,
        # so a media_assets entry without a pre-resolved media_id cannot be attached today.
        media_ids = [
            asset["media_id"]
            for asset in media_assets
            if isinstance(asset, dict) and asset.get("media_id")
        ]

        response = await x_integration.post_tweet(access_token, text, media_ids or None)
    except x_integration.XApiError as exc:
        out["status"] = "failed"
        out["error_message"] = f"{exc.kind}: {exc.message}"
        return out

    tweet_id = response.get("data", {}).get("id")
    out["status"] = "published"
    out["published_at"] = datetime.now(timezone.utc).isoformat()
    if tweet_id:
        out["post_url"] = f"https://x.com/i/web/status/{tweet_id}"
    return out
