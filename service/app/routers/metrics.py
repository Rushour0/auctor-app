from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from service.app.metrics_aggregations import build_metrics_payload
from service.auctor.workflow import WorkflowStore

router = APIRouter(prefix="/api", tags=["metrics"])


def _workflow_store() -> WorkflowStore:
    store = WorkflowStore()
    store.ensure_indexes()
    return store


# NOTE: the auth unit will optionally layer Depends(require_operator) onto these
# read endpoints; this unit intentionally ships them un-gated.
@router.get("/metrics")
async def metrics(
    workspace_id: str = Query(..., min_length=1),
    platform: Literal["x", "linkedin"] | None = None,
) -> dict:
    """Return the aggregated metrics + COGS payload for one workspace (optionally per-platform)."""
    if not workspace_id.strip():
        raise HTTPException(status_code=400, detail="workspace_id must not be blank")
    return await run_in_threadpool(
        lambda: build_metrics_payload(_workflow_store().db, workspace_id, platform)
    )


@router.get("/metrics/export")
async def export_metrics(
    workspace_id: str = Query(..., min_length=1),
    platform: Literal["x", "linkedin"] | None = None,
) -> dict:
    """Return the same metrics payload wrapped in an explicit, versioned export envelope."""
    if not workspace_id.strip():
        raise HTTPException(status_code=400, detail="workspace_id must not be blank")
    payload = await run_in_threadpool(
        lambda: build_metrics_payload(_workflow_store().db, workspace_id, platform)
    )
    return {"schema": "auctor.metrics.v1", "payload": payload}
