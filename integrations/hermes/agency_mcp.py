#!/usr/bin/env python3
"""Auctor's stdio MCP bridge for Hermes Agent."""

import sys
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from service.auctor.collectors.github import GitHubCollector  # noqa: E402
from service.auctor.collectors.linkup import LinkupCollector  # noqa: E402
from service.auctor.collectors.posthog import PostHogCollector  # noqa: E402
from service.auctor.config import get_settings  # noqa: E402
from service.auctor.memory import AuctorMemory  # noqa: E402
from service.auctor.workflow import (  # noqa: E402
    ApprovalRecord,
    FleetIntake,
    PublishRecord,
    WorkflowArtifact,
    WorkflowEvent,
    WorkflowStore,
)

mcp = FastMCP("auctor-memory")


def workflow_store() -> WorkflowStore:
    store = WorkflowStore(get_settings())
    store.ensure_indexes()
    return store


@mcp.tool()
def start_fleet(intake: dict) -> dict:
    """Idempotently persist fleet intake and initialize both pipelines per client."""
    return workflow_store().start_fleet(FleetIntake.model_validate(intake))


@mcp.tool()
def save_workflow_artifact(artifact: dict) -> dict:
    """Persist a versioned specialist artifact in MongoDB."""
    return workflow_store().save_artifact(WorkflowArtifact.model_validate(artifact))


@mcp.tool()
def record_workflow_event(event: dict) -> dict:
    """Persist an idempotent workflow event and update pipeline state."""
    return workflow_store().record_event(WorkflowEvent.model_validate(event))


@mcp.tool()
def save_approval_record(approval: dict) -> dict:
    """Persist an approval request or decision tied to one immutable artifact."""
    return workflow_store().save_approval(ApprovalRecord.model_validate(approval))


@mcp.tool()
def save_publish_result(publish: dict) -> dict:
    """Persist an explicit per-platform publish result."""
    return workflow_store().save_publish(PublishRecord.model_validate(publish))


@mcp.tool()
def get_workflow_status(workspace_id: str, fleet_id: str | None = None) -> dict:
    """Return persisted fleet, pipeline, artifact, event, approval, and post counts."""
    return workflow_store().status(workspace_id, fleet_id)


@mcp.tool()
def enqueue_due_content_loops(
    workspace_id: str | None = None, interval_hours: int = 6, batch_size: int = 100
) -> dict:
    """Atomically enqueue cadence triggers for active content loops that are due."""
    triggers = workflow_store().enqueue_due_content_loops(
        workspace_id=workspace_id,
        interval_hours=interval_hours,
        batch_size=batch_size,
    )
    return {"enqueued": len(triggers), "triggers": triggers}


@mcp.tool()
def schedule_content_loop(
    workspace_id: str, client_id: str, next_content_check_at: str | None = None
) -> dict:
    """Activate a client's content loop and set its next UTC cadence check."""
    scheduled = (
        datetime.fromisoformat(next_content_check_at.replace("Z", "+00:00"))
        if next_content_check_at
        else None
    )
    return workflow_store().schedule_content_loop(workspace_id, client_id, scheduled)


@mcp.tool()
def get_pending_workflow_triggers(workspace_id: str | None = None, limit: int = 100) -> dict:
    """List pending cadence triggers for Hermes to consume."""
    triggers = workflow_store().pending_triggers(workspace_id=workspace_id, limit=limit)
    return {"count": len(triggers), "triggers": triggers}


@mcp.tool()
def acknowledge_workflow_trigger(workspace_id: str, trigger_id: str, status: str) -> dict:
    """Mark a cadence trigger running, completed, or failed after Hermes handles it."""
    if status not in {"running", "completed", "failed"}:
        raise ValueError("status must be running, completed, or failed")
    return workflow_store().acknowledge_trigger(workspace_id, trigger_id, status)  # type: ignore[arg-type]


@mcp.tool()
def sync_github(
    workspace_id: str,
    repositories: list[str] | None = None,
    username: str | None = None,
    target_branch: str = "main",
    since_days: int = 30,
) -> dict:
    """Collect PRs merged into main since the last successful check."""
    result = GitHubCollector().collect(
        workspace_id=workspace_id,
        repositories=repositories,
        username=username,
        target_branch=target_branch,
        since_days=since_days,
    )
    return result.model_dump(mode="json")


@mcp.tool()
def verify_linkup_connection(workspace_id: str) -> dict:
    """Validate the Linkup API key and return the current credit balance."""
    return LinkupCollector().verify_authentication(workspace_id)


@mcp.tool()
def sync_industry_trends(
    workspace_id: str,
    topics: list[str],
    queries: list[str] | None = None,
    depth: str = "standard",
    max_results: int = 10,
    lookback_days: int = 14,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict:
    """Collect current, cited industry sources with Linkup."""
    result = LinkupCollector().collect(
        workspace_id=workspace_id,
        topics=topics,
        queries=queries,
        depth=depth,
        max_results=max_results,
        lookback_days=lookback_days,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
    )
    return result.model_dump(mode="json")


@mcp.tool()
def verify_posthog_connection(workspace_id: str) -> dict:
    """Validate the configured PostHog personal API key and project access."""
    return PostHogCollector().verify_authentication(workspace_id)


@mcp.tool()
def sync_posthog(
    workspace_id: str,
    since_days: int = 7,
    limit: int = 10_000,
) -> dict:
    """Collect PostHog product events and event-count metrics since the last successful check."""
    result = PostHogCollector().collect(
        workspace_id=workspace_id,
        since_days=since_days,
        limit=limit,
    )
    return result.model_dump(mode="json")


@mcp.tool()
def get_collection_status(workspace_id: str) -> dict:
    """Return Mongo record counts and collector freshness for one workspace."""
    return AuctorMemory(get_settings()).status(workspace_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
