from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from service.auctor.collectors.linkup import LinkupAPIError, LinkupCollector
from service.auctor.workflow import (
    ApprovalRecord,
    FleetIntake,
    PublishRecord,
    WorkflowArtifact,
    WorkflowEvent,
    WorkflowStore,
)

from .config import settings
from .onboarding import OnboardingDraft, OnboardingSubmission
from .routers.auth import require_operator, router as auth_router
from .routers.conversations import router as conversations_router
from .routers.metrics import router as metrics_router
from .routers.posts import router as posts_router
from .routers.x_oauth import router as x_oauth_router

VERSION = "0.0.1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.mongo = AsyncIOMotorClient(settings.mongodb_uri)
    app.state.db = app.state.mongo[settings.mongodb_db]
    yield
    app.state.mongo.close()


app = FastAPI(title="Auctor Service", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(x_oauth_router)
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(metrics_router)
app.include_router(posts_router)


class LinkupSyncRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    topics: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    depth: Literal["fast", "standard", "deep"] = "standard"
    max_results: int = Field(default=10, ge=1, le=100)
    lookback_days: int = Field(default=14, ge=1, le=365)
    include_domains: list[str] = Field(default_factory=list, max_length=100)
    exclude_domains: list[str] = Field(default_factory=list)


def _workflow_store() -> WorkflowStore:
    store = WorkflowStore()
    store.ensure_indexes()
    return store


def _linkup_http_error(error: Exception) -> HTTPException:
    if isinstance(error, LinkupAPIError):
        status_code = error.status_code if 400 <= error.status_code < 500 else 502
        return HTTPException(
            status_code=status_code,
            detail={"provider": "linkup", "code": error.code, "message": str(error)},
        )
    return HTTPException(status_code=400, detail=str(error))


@app.get("/health")
async def health() -> dict:
    try:
        await app.state.db.command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False
    return {"status": "ok" if mongo_ok else "degraded", "mongo": mongo_ok}


@app.get("/version")
async def version() -> dict:
    return {"auctor": VERSION, "env": settings.agency_env}


@app.get("/api/fleets")
async def list_fleets(operator: dict = Depends(require_operator)) -> dict:
    fleets = await app.state.db.fleet_runs.find({}, {"_id": 0}).to_list(length=100)
    return {"fleets": fleets}


@app.put("/api/onboarding/drafts")
async def save_onboarding_draft(draft: OnboardingDraft) -> dict:
    """Save an incomplete onboarding form without starting agent work."""
    draft_id = draft.draft_id or f"draft_{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    await app.state.db.onboarding_drafts.update_one(
        {"workspace_id": draft.workspace_id, "draft_id": draft_id},
        {
            "$set": {"payload": draft.payload, "updated_at": now},
            "$setOnInsert": {
                "workspace_id": draft.workspace_id,
                "draft_id": draft_id,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return {"draft_id": draft_id, "saved_at": now, "status": "draft"}


@app.post("/api/onboarding/submit", status_code=201)
async def submit_onboarding(submission: OnboardingSubmission) -> dict:
    """Validate onboarding, persist the source brief, and initialize both client pipelines."""
    client_id, fleet_id = submission.identifiers()
    intake = submission.to_fleet_intake(client_id, fleet_id)
    try:
        result = await run_in_threadpool(_workflow_store().start_fleet, intake)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    now = datetime.now(timezone.utc)
    await app.state.db.onboarding_submissions.update_one(
        {"workspace_id": submission.workspace_id, "client_id": client_id},
        {
            "$set": {
                "fleet_id": fleet_id,
                "submission": submission.model_dump(mode="python"),
                "status": "submitted",
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return {
        **result,
        "workspace_id": submission.workspace_id,
        "client_id": client_id,
        "next_step": "research",
    }


@app.post("/api/workflows/fleets")
async def start_fleet(intake: FleetIntake, operator: dict = Depends(require_operator)) -> dict:
    """Create an idempotent fleet intake and both pipeline records per client."""
    try:
        return await run_in_threadpool(_workflow_store().start_fleet, intake)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/workflows/artifacts")
async def save_workflow_artifact(
    artifact: WorkflowArtifact, operator: dict = Depends(require_operator)
) -> dict:
    """Persist a versioned specialist artifact and advance its pipeline pointer."""
    try:
        return await run_in_threadpool(_workflow_store().save_artifact, artifact)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/workflows/events")
async def record_workflow_event(
    event: WorkflowEvent, operator: dict = Depends(require_operator)
) -> dict:
    """Persist one idempotent lifecycle event and its pipeline transition."""
    return await run_in_threadpool(_workflow_store().record_event, event)


@app.get("/api/workflows/events")
async def list_workflow_events(
    workspace_id: str | None = None,
    limit: int = 100,
    operator: dict = Depends(require_operator),
) -> list[dict]:
    """Conversations feed — recent fleet_events, newest-first."""
    return await run_in_threadpool(_workflow_store().list_events, workspace_id, limit)


class TriggerAck(BaseModel):
    workspace_id: str = Field(min_length=1)
    trigger_id: str = Field(min_length=1)
    status: Literal["running", "completed", "failed"]


@app.get("/api/workflows/triggers")
async def list_workflow_triggers(
    workspace_id: str | None = None,
    limit: int = 100,
    operator: dict = Depends(require_operator),
) -> list[dict]:
    """Crons page — every scheduled content-loop trigger, newest-first."""
    return await run_in_threadpool(_workflow_store().list_triggers, workspace_id, limit)


@app.post("/api/workflows/triggers/ack")
async def ack_workflow_trigger(
    ack: TriggerAck, operator: dict = Depends(require_operator)
) -> dict:
    """Move a pending trigger to running/completed/failed."""
    try:
        return await run_in_threadpool(
            _workflow_store().acknowledge_trigger, ack.workspace_id, ack.trigger_id, ack.status
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/workflows/posts")
async def list_workflow_posts(
    workspace_id: str | None = None,
    limit: int = 100,
    operator: dict = Depends(require_operator),
) -> list[dict]:
    """Posts page — recent content_posts, newest-first, flat-array contract."""
    return await run_in_threadpool(_workflow_store().list_posts, workspace_id, limit)


@app.put("/api/workflows/approvals/{approval_id}")
async def save_approval(
    approval_id: str, approval: ApprovalRecord, operator: dict = Depends(require_operator)
) -> dict:
    if approval_id != approval.approval_id:
        raise HTTPException(status_code=400, detail="approval_id path/body mismatch")
    return await run_in_threadpool(_workflow_store().save_approval, approval)


@app.put("/api/workflows/posts/{post_id}/platforms/{platform}")
async def save_publish_result(
    post_id: str,
    platform: str,
    publish: PublishRecord,
    operator: dict = Depends(require_operator),
) -> dict:
    if post_id != publish.post_id or platform != publish.platform:
        raise HTTPException(status_code=400, detail="post/platform path/body mismatch")
    return await run_in_threadpool(_workflow_store().save_publish, publish)


@app.get("/api/workflows/status/{workspace_id}")
async def workflow_status(
    workspace_id: str,
    fleet_id: str | None = None,
    operator: dict = Depends(require_operator),
) -> dict:
    return await run_in_threadpool(_workflow_store().status, workspace_id, fleet_id)


@app.get("/api/workflows/runs/{run_id}")
async def workflow_run(run_id: str, workspace_id: str) -> dict:
    """Return an ordered run trace plus cost, token, latency, and outcome totals."""
    try:
        return await run_in_threadpool(_workflow_store().run_observability, workspace_id, run_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/workflows/runs")
async def workflow_runs(workspace_id: str, limit: int = 50) -> dict:
    """Return recent correlated runs and task-level scoring metrics."""
    return await run_in_threadpool(_workflow_store().recent_runs, workspace_id, limit)


@app.post("/api/integrations/linkup/verify")
async def verify_linkup(
    workspace_id: str, operator: dict = Depends(require_operator)
) -> dict:
    """Verify Linkup credentials without consuming a search request."""
    try:
        return await run_in_threadpool(LinkupCollector().verify_authentication, workspace_id)
    except (LinkupAPIError, ValueError) as error:
        raise _linkup_http_error(error) from error


@app.post("/api/integrations/linkup/sync")
async def sync_linkup(
    request: LinkupSyncRequest, operator: dict = Depends(require_operator)
) -> dict:
    """Collect current industry sources and persist their provenance in MongoDB."""
    try:
        result = await run_in_threadpool(
            LinkupCollector().collect,
            workspace_id=request.workspace_id,
            topics=request.topics,
            queries=request.queries,
            depth=request.depth,
            max_results=request.max_results,
            lookback_days=request.lookback_days,
            include_domains=request.include_domains,
            exclude_domains=request.exclude_domains,
        )
        return result.model_dump(mode="json")
    except (LinkupAPIError, ValueError) as error:
        raise _linkup_http_error(error) from error
