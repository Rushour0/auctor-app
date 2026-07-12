from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from service.auctor.config import Settings
from service.auctor.workflow import (
    ApprovalRecord,
    ClientIntake,
    FleetIntake,
    PublishRecord,
    WorkflowArtifact,
    WorkflowEvent,
    WorkflowStore,
)


def nested_set(document: dict[str, Any], path: str, value: Any) -> None:
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def dotted_get(document: dict[str, Any], key: str) -> Any:
    actual: Any = document
    for part in key.split("."):
        if not isinstance(actual, dict):
            return None
        actual = actual.get(part)
        if actual is None:
            return None
    return actual


def matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = dotted_get(document, key)
        if isinstance(expected, dict):
            if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


class Result:
    def __init__(self, matched_count: int, upserted_id: str | None = None):
        self.matched_count = matched_count
        self.upserted_id = upserted_id


class Cursor(list):
    def sort(self, key: str, direction: int):
        return Cursor(sorted(self, key=lambda row: row.get(key), reverse=direction < 0))


class Collection:
    def __init__(self):
        self.documents: list[dict[str, Any]] = []

    def create_index(self, *_: Any, **__: Any) -> None:
        return None

    def update_one(
        self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> Result:
        document = next((row for row in self.documents if matches(row, query)), None)
        inserted = document is None
        if inserted:
            if not upsert:
                return Result(0)
            document = deepcopy(query)
            self.documents.append(document)
            for key, value in update.get("$setOnInsert", {}).items():
                nested_set(document, key, deepcopy(value))
        for key, value in update.get("$set", {}).items():
            nested_set(document, key, deepcopy(value))
        for key, value in update.get("$inc", {}).items():
            target = document
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = target.get(parts[-1], 0) + value
        return Result(0 if inserted else 1, "new" if inserted else None)

    def count_documents(self, query: dict[str, Any]) -> int:
        return sum(matches(row, query) for row in self.documents)

    def find(self, query: dict[str, Any], projection: dict[str, int] | None = None) -> Cursor:
        rows = [deepcopy(row) for row in self.documents if matches(row, query)]
        if projection and projection.get("_id") == 0:
            for row in rows:
                row.pop("_id", None)
        return Cursor(rows)

    def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], return_document: Any = None
    ) -> dict[str, Any] | None:
        document = next((row for row in self.documents if matches(row, query)), None)
        if document is None:
            return None
        for key, value in update.get("$set", {}).items():
            nested_set(document, key, deepcopy(value))
        return deepcopy(document)


class Database:
    def __init__(self):
        self._collections: dict[str, Collection] = {}

    def __getattr__(self, name: str) -> Collection:
        return self._collections.setdefault(name, Collection())


def store() -> WorkflowStore:
    settings = Settings(mongodb_uri="mongodb://unused")
    return WorkflowStore(settings=settings, database=Database())  # type: ignore[arg-type]


def intake() -> FleetIntake:
    return FleetIntake(
        workspace_id="workspace-1",
        fleet_id="fleet-1",
        clients=[
            ClientIntake(
                client_id="client-1",
                name="Kriti Agarwal",
                linkedin_url="https://linkedin.com/in/kriti",
                audience=["investors", "prospective customers"],
                self_reported_context={"role": "Amazon engineer", "startup": "SNYF"},
            )
        ],
    )


def test_fleet_start_is_idempotent_and_creates_two_pipelines() -> None:
    workflow = store()
    workflow.ensure_indexes()
    workflow.start_fleet(intake())
    workflow.start_fleet(intake())

    status = workflow.status("workspace-1", "fleet-1")
    assert status["counts"]["fleets"] == 1
    assert status["counts"]["pipelines"] == 2
    assert {row["pipeline"] for row in status["pipelines"]} == {"site_build", "content_loop"}


def test_artifacts_events_approvals_and_platform_results_are_upserted() -> None:
    workflow = store()
    workflow.start_fleet(intake())
    artifact = WorkflowArtifact(
        workspace_id="workspace-1",
        fleet_id="fleet-1",
        client_id="client-1",
        pipeline="site_build",
        artifact_type="client_research",
        artifact_id="research-1",
        producer="researcher",
        payload={"usable_voice_excerpt_count": 0},
    )
    workflow.save_artifact(artifact)
    workflow.save_artifact(artifact)

    event = WorkflowEvent(
        workspace_id="workspace-1",
        fleet_id="fleet-1",
        client_id="client-1",
        pipeline="site_build",
        event_type="client_blocked",
        idempotency_key="fleet-1:client-1:site:blocked:voice",
        payload={"status": "blocked", "cost_usd": 0.1},
    )
    workflow.record_event(event)
    workflow.record_event(event)
    workflow.save_approval(
        ApprovalRecord(
            workspace_id="workspace-1",
            fleet_id="fleet-1",
            client_id="client-1",
            pipeline="site_build",
            approval_id="approval-1",
            artifact_id="build-1",
        )
    )
    workflow.save_publish(
        PublishRecord(
            workspace_id="workspace-1",
            fleet_id="fleet-1",
            client_id="client-1",
            post_id="post-1",
            platform="x",
            status="published",
            platform_post_id="tweet-1",
            post_url="https://x.com/example/status/tweet-1",
        )
    )

    status = workflow.status("workspace-1", "fleet-1")
    assert status["counts"] == {
        "fleets": 1,
        "pipelines": 2,
        "artifacts": 1,
        "events": 1,
        "approvals": 1,
        "posts": 1,
        "triggers": 0,
    }
    site = next(row for row in status["pipelines"] if row["pipeline"] == "site_build")
    assert site["status"] == "blocked"
    assert site["usage"]["cost_usd"] == 0.1


def test_duplicate_client_ids_are_rejected() -> None:
    workflow = store()
    client = ClientIntake(client_id="same", name="One")
    duplicate = FleetIntake(
        workspace_id="workspace-1", fleet_id="fleet-1", clients=[client, client]
    )
    try:
        workflow.start_fleet(duplicate)
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("Expected duplicate client ids to be rejected")


def test_run_observability_aggregates_agent_cost_tokens_and_latency() -> None:
    workflow = store()
    workflow.start_fleet(intake())
    for event in (
        WorkflowEvent(
            workspace_id="workspace-1", fleet_id="fleet-1", client_id="client-1",
            pipeline="content_loop", run_id="run-1", stage_run_id="stage-1",
            agent="researcher", stage="research", outcome="succeeded",
            event_type="stage.completed", idempotency_key="run-1:research:1",
            duration_ms=1200, input_tokens=100, output_tokens=40, cached_tokens=10,
            cost_usd=0.03, model="test-model", provider="test-provider",
        ),
        WorkflowEvent(
            workspace_id="workspace-1", fleet_id="fleet-1", client_id="client-1",
            pipeline="content_loop", run_id="run-1", stage_run_id="stage-2",
            parent_event_id="stage-1", agent="writer", stage="draft", outcome="failed",
            event_type="stage.failed", idempotency_key="run-1:draft:1",
            duration_ms=800, input_tokens=200, output_tokens=80, cost_usd=0.07,
        ),
    ):
        workflow.record_event(event)

    run = workflow.run_observability("workspace-1", "run-1")
    assert run["summary"] == {
        "event_count": 2, "measured_steps": 2, "duration_ms": 2000,
        "wall_clock_duration_ms": 2000,
        "input_tokens": 300, "output_tokens": 120, "cached_tokens": 10,
        "cost_usd": 0.1, "outcomes": {"succeeded": 1, "failed": 1},
    }
    assert run["by_agent"]["researcher"]["cost_usd"] == 0.03
    assert run["by_agent"]["writer"]["duration_ms"] == 800
    pipeline = workflow.db.client_pipelines.documents[1]
    assert pipeline["usage"] == {
        "input_tokens": 300, "output_tokens": 120, "cached_tokens": 10,
        "latency_ms": 2000, "cost_usd": 0.1,
    }


def test_run_observability_rejects_unknown_run() -> None:
    workflow = store()
    try:
        workflow.run_observability("workspace-1", "missing")
    except ValueError as error:
        assert "not found" in str(error)
    else:
        raise AssertionError("Expected unknown run to be rejected")


def test_recent_runs_calculates_task_metrics_from_real_events() -> None:
    workflow = store()
    workflow.start_fleet(intake())
    for run_id, outcome, cost, duration in (
        ("run-success", "succeeded", 0.12, 60_000),
        ("run-failed", "failed", 0.08, 30_000),
    ):
        workflow.record_event(WorkflowEvent(
            workspace_id="workspace-1", fleet_id="fleet-1", client_id="client-1",
            pipeline="content_loop", run_id=run_id, agent="publisher", stage="publish",
            outcome=outcome, event_type="run.completed" if outcome == "succeeded" else "run.failed",
            idempotency_key=f"{run_id}:{outcome}", cost_usd=cost, duration_ms=duration,
        ))
    result = workflow.recent_runs("workspace-1")
    assert result["metrics"] == {
        "tasks_attempted": 2,
        "tasks_completed": 1,
        "task_success_rate_percent": 50.0,
        "average_cost_usd": 0.12,
        "average_measured_latency_ms": 45_000,
    }


def test_observed_stage_derives_duration_and_records_usage() -> None:
    workflow = store()
    workflow.start_fleet(intake())
    started = datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)
    workflow.start_stage(WorkflowEvent(
        workspace_id="workspace-1", fleet_id="fleet-1", client_id="client-1",
        pipeline="content_loop", run_id="run-timed", stage_run_id="stage-timed",
        agent="voice_writer", stage="draft", event_type="ignored",
        idempotency_key="run-timed:draft:started", started_at=started,
    ))
    result = workflow.complete_stage(WorkflowEvent(
        workspace_id="workspace-1", fleet_id="fleet-1", client_id="client-1",
        pipeline="content_loop", run_id="run-timed", stage_run_id="stage-timed",
        agent="voice_writer", stage="draft", outcome="succeeded",
        event_type="stage.completed", idempotency_key="run-timed:draft:completed",
        completed_at=started + timedelta(seconds=2), input_tokens=20, output_tokens=10,
        cost_usd=0.01,
    ))
    assert result["duration_ms"] == 2000


def test_scheduler_enqueues_each_due_window_once() -> None:
    workflow = store()
    workflow.start_fleet(intake())
    due = datetime(2026, 7, 12, 6, tzinfo=timezone.utc)
    workflow.schedule_content_loop("workspace-1", "client-1", due)
    content_loop = workflow.db.client_pipelines.documents[1]

    first = workflow.enqueue_due_content_loops(
        workspace_id="workspace-1", now=due, interval_hours=6
    )
    second = workflow.enqueue_due_content_loops(
        workspace_id="workspace-1", now=due, interval_hours=6
    )

    assert len(first) == 1
    assert second == []
    assert first[0]["trigger_id"] == "client-1:content_loop:2026-07-12T06:00:00+00:00"
    assert content_loop["next_content_check_at"] == datetime(2026, 7, 12, 12, tzinfo=timezone.utc)
    assert workflow.pending_triggers("workspace-1") == first
    workflow.acknowledge_trigger("workspace-1", first[0]["trigger_id"], "completed")
    assert workflow.pending_triggers("workspace-1") == []


def test_x_and_linkedin_cadences_advance_independently() -> None:
    workflow = store()
    workflow.start_fleet(intake())
    due = datetime(2026, 7, 12, 6, tzinfo=timezone.utc)
    workflow.schedule_content_loop("workspace-1", "client-1", due)
    content_loop = workflow.db.client_pipelines.documents[1]

    first_x = workflow.enqueue_due_content_loops(
        workspace_id="workspace-1", now=due, interval_hours=6, platform="x"
    )
    second_x = workflow.enqueue_due_content_loops(
        workspace_id="workspace-1", now=due, interval_hours=6, platform="x"
    )
    linkedin = workflow.enqueue_due_content_loops(
        workspace_id="workspace-1", now=due, interval_hours=6, platform="linkedin"
    )

    assert len(first_x) == 1
    assert second_x == []
    assert len(linkedin) == 1
    assert first_x[0]["trigger_id"] == "client-1:content_loop:x:2026-07-12T06:00:00+00:00"
    assert first_x[0]["platform"] == "x"
    assert linkedin[0]["trigger_id"] == "client-1:content_loop:linkedin:2026-07-12T06:00:00+00:00"
    assert linkedin[0]["platform"] == "linkedin"
    assert content_loop["platform_next_check"]["x"] == datetime(
        2026, 7, 12, 12, tzinfo=timezone.utc
    )


def test_generic_platform_none_path_unchanged() -> None:
    workflow = store()
    workflow.start_fleet(intake())
    due = datetime(2026, 7, 12, 6, tzinfo=timezone.utc)
    workflow.schedule_content_loop("workspace-1", "client-1", due)
    content_loop = workflow.db.client_pipelines.documents[1]

    triggers = workflow.enqueue_due_content_loops(
        workspace_id="workspace-1", now=due, interval_hours=6
    )

    assert len(triggers) == 1
    assert triggers[0]["trigger_id"] == "client-1:content_loop:2026-07-12T06:00:00+00:00"
    assert "platform" not in triggers[0]
    assert content_loop["next_content_check_at"] == datetime(2026, 7, 12, 12, tzinfo=timezone.utc)
