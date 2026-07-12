from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
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
async def list_fleets() -> dict:
    fleets = await app.state.db.fleet_runs.find({}, {"_id": 0}).to_list(length=100)
    return {"fleets": fleets}


@app.post("/api/workflows/fleets")
async def start_fleet(intake: FleetIntake) -> dict:
    """Create an idempotent fleet intake and both pipeline records per client."""
    try:
        return await run_in_threadpool(_workflow_store().start_fleet, intake)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/workflows/artifacts")
async def save_workflow_artifact(artifact: WorkflowArtifact) -> dict:
    """Persist a versioned specialist artifact and advance its pipeline pointer."""
    try:
        return await run_in_threadpool(_workflow_store().save_artifact, artifact)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/workflows/events")
async def record_workflow_event(event: WorkflowEvent) -> dict:
    """Persist one idempotent lifecycle event and its pipeline transition."""
    return await run_in_threadpool(_workflow_store().record_event, event)


@app.put("/api/workflows/approvals/{approval_id}")
async def save_approval(approval_id: str, approval: ApprovalRecord) -> dict:
    if approval_id != approval.approval_id:
        raise HTTPException(status_code=400, detail="approval_id path/body mismatch")
    return await run_in_threadpool(_workflow_store().save_approval, approval)


@app.put("/api/workflows/posts/{post_id}/platforms/{platform}")
async def save_publish_result(post_id: str, platform: str, publish: PublishRecord) -> dict:
    if post_id != publish.post_id or platform != publish.platform:
        raise HTTPException(status_code=400, detail="post/platform path/body mismatch")
    return await run_in_threadpool(_workflow_store().save_publish, publish)


@app.get("/api/workflows/status/{workspace_id}")
async def workflow_status(workspace_id: str, fleet_id: str | None = None) -> dict:
    return await run_in_threadpool(_workflow_store().status, workspace_id, fleet_id)


@app.post("/api/integrations/linkup/verify")
async def verify_linkup(workspace_id: str) -> dict:
    """Verify Linkup credentials without consuming a search request."""
    try:
        return await run_in_threadpool(LinkupCollector().verify_authentication, workspace_id)
    except (LinkupAPIError, ValueError) as error:
        raise _linkup_http_error(error) from error


@app.post("/api/integrations/linkup/sync")
async def sync_linkup(request: LinkupSyncRequest) -> dict:
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
