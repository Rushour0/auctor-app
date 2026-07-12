from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/posts", tags=["posts"])


@router.get("")
async def list_posts(
    request: Request,
    client_id: str | None = Query(None),
    status: str | None = Query(None),
    platform: Literal["x", "linkedin"] | None = Query(None),
    post_type: str | None = Query(None),
    workspace_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """List content_posts newest-first with optional per-field and per-platform filters."""
    query: dict = {}
    if client_id is not None:
        query["client_id"] = client_id
    if status is not None:
        query["status"] = status
    if post_type is not None:
        query["post_type"] = post_type
    if workspace_id is not None:
        query["workspace_id"] = workspace_id
    if platform is not None:
        # Per-platform contract: platform_status.{x,linkedin} sub-docs are written
        # independently by WorkflowStore.save_publish; never collapse to a boolean.
        query[f"platform_status.{platform}"] = {"$exists": True}

    db = request.app.state.db
    total = await db.content_posts.count_documents(query)
    cursor = (
        db.content_posts.find(query, {"_id": 0}).sort("updated_at", -1).skip(offset).limit(limit)
    )
    posts = await cursor.to_list(length=limit)
    return {"posts": posts, "total": total, "limit": limit, "offset": offset}


@router.get("/{post_id}")
async def get_post(request: Request, post_id: str) -> dict:
    """Fetch a single content post by its post_id (the collection's identity field)."""
    doc = await request.app.state.db.content_posts.find_one({"post_id": post_id}, {"_id": 0})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"post {post_id} not found")
    return doc
