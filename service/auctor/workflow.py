from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.database import Database

from .config import Settings, get_settings


Pipeline = Literal["site_build", "content_loop"]
EventOutcome = Literal["started", "succeeded", "failed", "blocked", "cancelled"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ClientIntake(BaseModel):
    client_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    linkedin_url: str | None = None
    site_url: str | None = None
    resume_url: str | None = None
    audience: list[str] = Field(default_factory=list)
    self_reported_context: dict[str, Any] = Field(default_factory=dict)


class FleetIntake(BaseModel):
    workspace_id: str = Field(min_length=1)
    fleet_id: str = Field(min_length=1)
    clients: list[ClientIntake] = Field(min_length=1)
    request: str | None = None


class WorkflowArtifact(BaseModel):
    workspace_id: str = Field(min_length=1)
    fleet_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    pipeline: Pipeline
    artifact_type: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    payload: dict[str, Any]
    producer: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    source_refs: list[str] = Field(default_factory=list)


class WorkflowEvent(BaseModel):
    workspace_id: str = Field(min_length=1)
    fleet_id: str = Field(min_length=1)
    event_id: str = Field(default_factory=lambda: f"event_{uuid4().hex[:16]}")
    event_type: str = Field(min_length=1)
    client_id: str | None = None
    pipeline: Pipeline | None = None
    run_id: str | None = None
    stage_run_id: str | None = None
    parent_event_id: str | None = None
    agent: str | None = None
    stage: str | None = None
    outcome: EventOutcome | None = None
    attempt: int = Field(default=1, ge=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    model: str | None = None
    provider: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)


class ApprovalRecord(BaseModel):
    workspace_id: str = Field(min_length=1)
    fleet_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    pipeline: Pipeline
    approval_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    channel: Literal["whatsapp", "web"] = "whatsapp"
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    decision_metadata: dict[str, Any] = Field(default_factory=dict)


class PublishRecord(BaseModel):
    workspace_id: str = Field(min_length=1)
    fleet_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    post_id: str = Field(min_length=1)
    platform: Literal["x", "linkedin", "web"]
    status: Literal["not_applicable", "pending", "published", "failed", "unknown"]
    platform_post_id: str | None = None
    post_url: str | None = None
    error_message: str | None = None
    provider_response: dict[str, Any] = Field(default_factory=dict)


class WorkflowStore:
    """The single code-owned persistence boundary for Hermes agency workflow state."""

    def __init__(self, settings: Settings | None = None, database: Database | None = None):
        self.settings = settings or get_settings()
        self._client: MongoClient | None = None
        if database is not None:
            self.db = database
        else:
            self._client = MongoClient(self.settings.mongodb_uri)
            self.db = self._client[self.settings.mongodb_db]

    def ensure_indexes(self) -> None:
        self.db.fleet_runs.create_index(
            [("workspace_id", ASCENDING), ("fleet_id", ASCENDING)], unique=True
        )
        self.db.client_pipelines.create_index(
            [("workspace_id", ASCENDING), ("client_id", ASCENDING), ("pipeline", ASCENDING)],
            unique=True,
        )
        self.db.workflow_artifacts.create_index(
            [("workspace_id", ASCENDING), ("artifact_id", ASCENDING), ("version", ASCENDING)],
            unique=True,
        )
        self.db.workflow_artifacts.create_index(
            [("client_id", ASCENDING), ("pipeline", ASCENDING), ("recorded_at", DESCENDING)]
        )
        self.db.fleet_events.create_index(
            [("workspace_id", ASCENDING), ("idempotency_key", ASCENDING)], unique=True
        )
        self.db.fleet_events.create_index(
            [("workspace_id", ASCENDING), ("run_id", ASCENDING), ("recorded_at", ASCENDING)]
        )
        self.db.approval_requests.create_index(
            [("workspace_id", ASCENDING), ("approval_id", ASCENDING)], unique=True
        )
        self.db.content_posts.create_index(
            [("workspace_id", ASCENDING), ("post_id", ASCENDING)], unique=True
        )
        self.db.workflow_triggers.create_index(
            [("workspace_id", ASCENDING), ("trigger_id", ASCENDING)], unique=True
        )
        self.db.workflow_triggers.create_index(
            [("status", ASCENDING), ("scheduled_for", ASCENDING)]
        )

    def start_fleet(self, intake: FleetIntake) -> dict[str, Any]:
        client_ids = [client.client_id for client in intake.clients]
        if len(client_ids) != len(set(client_ids)):
            raise ValueError("client_id values must be unique within a fleet")
        now = utc_now()
        fleet_key = {"workspace_id": intake.workspace_id, "fleet_id": intake.fleet_id}
        self.db.fleet_runs.update_one(
            fleet_key,
            {
                "$set": {"request": intake.request, "updated_at": now},
                "$setOnInsert": {**fleet_key, "status": "active", "created_at": now},
            },
            upsert=True,
        )
        for client in intake.clients:
            client_doc = client.model_dump(mode="python")
            for pipeline, status in (("site_build", "queued"), ("content_loop", "not_started")):
                key = {
                    "workspace_id": intake.workspace_id,
                    "client_id": client.client_id,
                    "pipeline": pipeline,
                }
                self.db.client_pipelines.update_one(
                    key,
                    {
                        "$set": {
                            "fleet_id": intake.fleet_id,
                            "intake": client_doc,
                            "updated_at": now,
                        },
                        "$setOnInsert": {
                            **key,
                            "status": status,
                            "retry_count": 0,
                            "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                            "created_at": now,
                        },
                    },
                    upsert=True,
                )
        return {
            "fleet_id": intake.fleet_id,
            "client_count": len(intake.clients),
            "status": "active",
        }

    def save_artifact(self, artifact: WorkflowArtifact) -> dict[str, Any]:
        now = utc_now()
        key = {
            "workspace_id": artifact.workspace_id,
            "artifact_id": artifact.artifact_id,
            "version": artifact.version,
        }
        document = artifact.model_dump(mode="python")
        self.db.workflow_artifacts.update_one(
            key,
            {"$set": {**document, "updated_at": now}, "$setOnInsert": {"recorded_at": now}},
            upsert=True,
        )
        pipeline_key = {
            "workspace_id": artifact.workspace_id,
            "client_id": artifact.client_id,
            "pipeline": artifact.pipeline,
        }
        result = self.db.client_pipelines.update_one(
            pipeline_key,
            {
                "$set": {
                    "fleet_id": artifact.fleet_id,
                    "current_artifact_type": artifact.artifact_type,
                    "current_artifact_id": artifact.artifact_id,
                    "updated_at": now,
                }
            },
        )
        if result.matched_count == 0:
            raise ValueError(
                "client pipeline does not exist; start the fleet before saving artifacts"
            )
        return {
            "artifact_id": artifact.artifact_id,
            "version": artifact.version,
            "recorded_at": now,
        }

    def record_event(self, event: WorkflowEvent) -> dict[str, Any]:
        now = utc_now()
        key = {"workspace_id": event.workspace_id, "idempotency_key": event.idempotency_key}
        result = self.db.fleet_events.update_one(
            key,
            {"$setOnInsert": {**event.model_dump(mode="python"), "recorded_at": now}},
            upsert=True,
        )
        if result.upserted_id is not None and event.client_id and event.pipeline:
            updates: dict[str, Any] = {"last_event_type": event.event_type, "updated_at": now}
            if "status" in event.payload:
                updates["status"] = event.payload["status"]
            if "retry_count" in event.payload:
                updates["retry_count"] = event.payload["retry_count"]
            if "next_content_check_at" in event.payload:
                updates["next_content_check_at"] = event.payload["next_content_check_at"]
            event_cost = event.cost_usd + float(event.payload.get("cost_usd", 0.0))
            usage_increment = {
                "usage.input_tokens": event.input_tokens,
                "usage.output_tokens": event.output_tokens,
                "usage.cached_tokens": event.cached_tokens,
                "usage.latency_ms": event.duration_ms or 0,
                "usage.cost_usd": event_cost,
            }
            if any(usage_increment.values()):
                self.db.client_pipelines.update_one(
                    {
                        "workspace_id": event.workspace_id,
                        "client_id": event.client_id,
                        "pipeline": event.pipeline,
                    },
                    {"$set": updates, "$inc": usage_increment},
                )
            else:
                self.db.client_pipelines.update_one(
                    {
                        "workspace_id": event.workspace_id,
                        "client_id": event.client_id,
                        "pipeline": event.pipeline,
                    },
                    {"$set": updates},
                )
        return {"event_id": event.event_id, "recorded_at": now}

    def start_stage(self, event: WorkflowEvent) -> dict[str, Any]:
        """Start a measured agent stage; completion can derive wall-clock latency."""
        if not event.run_id or not event.stage_run_id or not event.agent or not event.stage:
            raise ValueError("run_id, stage_run_id, agent, and stage are required")
        started_at = event.started_at or utc_now()
        observed = event.model_copy(
            update={
                "event_type": "stage.started",
                "outcome": "started",
                "started_at": started_at,
            }
        )
        result = self.record_event(observed)
        return {
            **result,
            "run_id": observed.run_id,
            "stage_run_id": observed.stage_run_id,
            "started_at": started_at,
        }

    def complete_stage(self, event: WorkflowEvent) -> dict[str, Any]:
        """Finish a measured stage and automatically calculate latency from its start event."""
        if not event.run_id or not event.stage_run_id:
            raise ValueError("run_id and stage_run_id are required")
        starts = list(
            self.db.fleet_events.find(
                {
                    "workspace_id": event.workspace_id,
                    "run_id": event.run_id,
                    "stage_run_id": event.stage_run_id,
                    "outcome": "started",
                },
                {"_id": 0},
            )
        )
        if not starts:
            raise ValueError("stage start event not found")
        started_at = starts[0]["started_at"]
        completed_at = event.completed_at or utc_now()
        duration_ms = event.duration_ms
        if duration_ms is None:
            duration_ms = max(0, round((completed_at - started_at).total_seconds() * 1000))
        observed = event.model_copy(
            update={
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": duration_ms,
            }
        )
        result = self.record_event(observed)
        return {
            **result,
            "run_id": observed.run_id,
            "stage_run_id": observed.stage_run_id,
            "duration_ms": duration_ms,
            "cost_usd": observed.cost_usd,
        }

    def run_observability(self, workspace_id: str, run_id: str) -> dict[str, Any]:
        """Return a reconstructable run timeline with cost, latency, and outcome totals."""
        query = {"workspace_id": workspace_id, "run_id": run_id}
        events = list(self.db.fleet_events.find(query, {"_id": 0}).sort("recorded_at", ASCENDING))
        if not events:
            raise ValueError("workflow run not found")

        durations = [
            event["duration_ms"] for event in events if event.get("duration_ms") is not None
        ]
        starts = [event["started_at"] for event in events if event.get("started_at") is not None]
        completions = [
            event["completed_at"] for event in events if event.get("completed_at") is not None
        ]
        wall_clock_duration_ms = (
            max(0, round((max(completions) - min(starts)).total_seconds() * 1000))
            if starts and completions
            else sum(durations)
        )
        outcomes: dict[str, int] = {}
        agents: dict[str, dict[str, Any]] = {}
        for event in events:
            outcome = event.get("outcome")
            if outcome:
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
            agent = event.get("agent") or "unattributed"
            aggregate = agents.setdefault(
                agent,
                {
                    "events": 0,
                    "duration_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_tokens": 0,
                    "cost_usd": 0.0,
                },
            )
            aggregate["events"] += 1
            aggregate["duration_ms"] += event.get("duration_ms") or 0
            aggregate["input_tokens"] += event.get("input_tokens") or 0
            aggregate["output_tokens"] += event.get("output_tokens") or 0
            aggregate["cached_tokens"] += event.get("cached_tokens") or 0
            aggregate["cost_usd"] += event.get("cost_usd") or 0.0

        return {
            "workspace_id": workspace_id,
            "run_id": run_id,
            "summary": {
                "event_count": len(events),
                "measured_steps": len(durations),
                "duration_ms": sum(durations),
                "wall_clock_duration_ms": wall_clock_duration_ms,
                "input_tokens": sum(event.get("input_tokens") or 0 for event in events),
                "output_tokens": sum(event.get("output_tokens") or 0 for event in events),
                "cached_tokens": sum(event.get("cached_tokens") or 0 for event in events),
                "cost_usd": sum(event.get("cost_usd") or 0.0 for event in events),
                "outcomes": outcomes,
            },
            "by_agent": agents,
            "events": events,
        }

    def recent_runs(self, workspace_id: str, limit: int = 50) -> dict[str, Any]:
        """Return recent measured runs and judge-facing task metrics for a workspace."""
        events = list(
            self.db.fleet_events.find({"workspace_id": workspace_id}, {"_id": 0}).sort(
                "recorded_at", DESCENDING
            )
        )
        run_ids: list[str] = []
        for event in events:
            run_id = event.get("run_id")
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)
            if len(run_ids) >= max(1, min(limit, 200)):
                break
        runs = [self.run_observability(workspace_id, run_id) for run_id in run_ids]
        completed = [
            run
            for run in runs
            if any(
                event.get("event_type") == "run.completed"
                or (event.get("stage") == "publish" and event.get("outcome") == "succeeded")
                for event in run["events"]
            )
        ]
        measured = [run for run in runs if run["summary"]["measured_steps"] > 0]
        return {
            "workspace_id": workspace_id,
            "metrics": {
                "tasks_attempted": len(runs),
                "tasks_completed": len(completed),
                "task_success_rate_percent": round(len(completed) / len(runs) * 100, 1)
                if runs
                else None,
                "average_cost_usd": round(
                    sum(run["summary"]["cost_usd"] for run in completed) / len(completed), 6
                )
                if completed
                else None,
                "average_measured_latency_ms": round(
                    sum(run["summary"]["wall_clock_duration_ms"] for run in measured)
                    / len(measured)
                )
                if measured
                else None,
            },
            "runs": runs,
        }

    def save_approval(self, approval: ApprovalRecord) -> dict[str, Any]:
        now = utc_now()
        key = {"workspace_id": approval.workspace_id, "approval_id": approval.approval_id}
        self.db.approval_requests.update_one(
            key,
            {
                "$set": {**approval.model_dump(mode="python"), "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return {"approval_id": approval.approval_id, "status": approval.status, "updated_at": now}

    def save_publish(self, publish: PublishRecord) -> dict[str, Any]:
        now = utc_now()
        key = {"workspace_id": publish.workspace_id, "post_id": publish.post_id}
        base = {
            "workspace_id": publish.workspace_id,
            "fleet_id": publish.fleet_id,
            "client_id": publish.client_id,
            "post_id": publish.post_id,
        }
        platform = publish.model_dump(mode="python", exclude={"provider_response"})
        platform["recorded_at"] = now
        self.db.content_posts.update_one(
            key,
            {
                "$set": {
                    **base,
                    f"platform_status.{publish.platform}": platform,
                    f"provider_responses.{publish.platform}": publish.provider_response,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return {"post_id": publish.post_id, "platform": publish.platform, "status": publish.status}

    def enqueue_due_content_loops(
        self,
        workspace_id: str | None = None,
        now: datetime | None = None,
        interval_hours: int = 6,
        batch_size: int = 100,
        platform: Literal["x", "linkedin"] | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically advance due pipelines and enqueue one trigger per cadence window.

        When ``platform`` is set the cadence is tracked on a per-platform sub-doc field
        ``platform_next_check.<platform>`` so ``x`` and ``linkedin`` advance independently;
        when it is ``None`` the generic flat ``next_content_check_at`` cadence is used.
        """
        current = (now or utc_now()).astimezone(timezone.utc)
        field = f"platform_next_check.{platform}" if platform else "next_content_check_at"
        due_query: dict[str, Any] = {
            "pipeline": "content_loop",
            "status": "active",
            field: {"$lte": current},
        }
        if workspace_id:
            due_query["workspace_id"] = workspace_id
        candidates = list(
            self.db.client_pipelines.find(due_query, {"_id": 0}).sort(field, ASCENDING)
        )[: max(1, min(batch_size, 1000))]
        enqueued: list[dict[str, Any]] = []
        next_check = current + timedelta(hours=max(1, interval_hours))
        window = current.replace(minute=0, second=0, microsecond=0).isoformat()
        for candidate in candidates:
            identity = {
                "workspace_id": candidate["workspace_id"],
                "client_id": candidate["client_id"],
                "pipeline": "content_loop",
                "status": "active",
                field: {"$lte": current},
            }
            claimed = self.db.client_pipelines.find_one_and_update(
                identity,
                {"$set": {field: next_check, "updated_at": current}},
                return_document=ReturnDocument.AFTER,
            )
            if claimed is None:
                continue
            if platform:
                trigger_id = f"{candidate['client_id']}:content_loop:{platform}:{window}"
            else:
                trigger_id = f"{candidate['client_id']}:content_loop:{window}"
            trigger = {
                "workspace_id": candidate["workspace_id"],
                "fleet_id": candidate["fleet_id"],
                "client_id": candidate["client_id"],
                "pipeline": "content_loop",
                "trigger_id": trigger_id,
                "trigger_type": "cadence",
                "status": "pending",
                "scheduled_for": current,
                "next_content_check_at": next_check,
                "created_at": current,
            }
            if platform is not None:
                trigger["platform"] = platform
            result = self.db.workflow_triggers.update_one(
                {"workspace_id": candidate["workspace_id"], "trigger_id": trigger_id},
                {"$setOnInsert": trigger},
                upsert=True,
            )
            if result.upserted_id is None:
                continue
            self.record_event(
                WorkflowEvent(
                    workspace_id=candidate["workspace_id"],
                    fleet_id=candidate["fleet_id"],
                    client_id=candidate["client_id"],
                    pipeline="content_loop",
                    event_type="content_loop_scheduled",
                    idempotency_key=f"trigger:{trigger_id}",
                    payload={"status": "active", "next_content_check_at": next_check},
                )
            )
            enqueued.append(trigger)
        return enqueued

    def schedule_content_loop(
        self,
        workspace_id: str,
        client_id: str,
        next_content_check_at: datetime | None = None,
    ) -> dict[str, Any]:
        requested = next_content_check_at or utc_now()
        if requested.tzinfo is None:
            raise ValueError("next_content_check_at must include a timezone")
        scheduled_for = requested.astimezone(timezone.utc)
        now = utc_now()
        result = self.db.client_pipelines.update_one(
            {"workspace_id": workspace_id, "client_id": client_id, "pipeline": "content_loop"},
            {
                "$set": {
                    "status": "active",
                    "next_content_check_at": scheduled_for,
                    "platform_next_check.x": scheduled_for,
                    "platform_next_check.linkedin": scheduled_for,
                    "updated_at": now,
                }
            },
        )
        if result.matched_count == 0:
            raise ValueError("content-loop pipeline not found")
        return {
            "workspace_id": workspace_id,
            "client_id": client_id,
            "status": "active",
            "next_content_check_at": scheduled_for,
        }

    def pending_triggers(
        self, workspace_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"status": "pending"}
        if workspace_id:
            query["workspace_id"] = workspace_id
        return list(
            self.db.workflow_triggers.find(query, {"_id": 0}).sort("scheduled_for", ASCENDING)
        )[: max(1, min(limit, 1000))]

    def list_triggers(
        self, workspace_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Every trigger regardless of status, newest-first — the Crons page's full queue view
        (``pending_triggers`` above is pending-only, oldest-first, for the scheduler's own poll)."""
        query: dict[str, Any] = {}
        if workspace_id:
            query["workspace_id"] = workspace_id
        return list(
            self.db.workflow_triggers.find(query, {"_id": 0})
            .sort("scheduled_for", DESCENDING)
            .limit(max(1, min(limit, 1000)))
        )

    def list_events(
        self, workspace_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Recent fleet_events, newest-first — the Conversations feed."""
        query: dict[str, Any] = {}
        if workspace_id:
            query["workspace_id"] = workspace_id
        return list(
            self.db.fleet_events.find(query, {"_id": 0})
            .sort("recorded_at", DESCENDING)
            .limit(max(1, min(limit, 1000)))
        )

    def list_posts(self, workspace_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Recent content_posts, newest-first — the Posts page's flat list contract."""
        query: dict[str, Any] = {}
        if workspace_id:
            query["workspace_id"] = workspace_id
        return list(
            self.db.content_posts.find(query, {"_id": 0})
            .sort("updated_at", DESCENDING)
            .limit(max(1, min(limit, 1000)))
        )

    def acknowledge_trigger(
        self, workspace_id: str, trigger_id: str, status: Literal["running", "completed", "failed"]
    ) -> dict[str, Any]:
        now = utc_now()
        result = self.db.workflow_triggers.update_one(
            {"workspace_id": workspace_id, "trigger_id": trigger_id},
            {"$set": {"status": status, "updated_at": now}},
        )
        if result.matched_count == 0:
            raise ValueError("workflow trigger not found")
        return {"trigger_id": trigger_id, "status": status, "updated_at": now}

    def status(self, workspace_id: str, fleet_id: str | None = None) -> dict[str, Any]:
        query: dict[str, Any] = {"workspace_id": workspace_id}
        if fleet_id:
            query["fleet_id"] = fleet_id
        return {
            "workspace_id": workspace_id,
            "fleet_id": fleet_id,
            "counts": {
                "fleets": self.db.fleet_runs.count_documents(query),
                "pipelines": self.db.client_pipelines.count_documents(query),
                "artifacts": self.db.workflow_artifacts.count_documents(query),
                "events": self.db.fleet_events.count_documents(query),
                "approvals": self.db.approval_requests.count_documents(query),
                "posts": self.db.content_posts.count_documents(query),
                "triggers": self.db.workflow_triggers.count_documents(query),
            },
            "pipelines": list(
                self.db.client_pipelines.find(query, {"_id": 0}).sort("updated_at", DESCENDING)
            ),
        }
