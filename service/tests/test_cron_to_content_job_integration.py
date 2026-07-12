"""Integration coverage for "can a cron actually produce a post for a client".

Two things are exercised together against the same real WorkflowStore + fake-Mongo
double (service/tests/_fake_mongo.py — the sync-pymongo substrate CI's headless run
uses in place of a real mongod, see that module's docstring):

1. The scheduler side: WorkflowStore.enqueue_due_content_loops actually creates
   per-platform workflow_triggers when a content-loop pipeline is due.
2. The content-job side: ContentAgencyRunner actually researches (Linkup faked at
   the network boundary, same convention as test_linkup_api.py/test_demo.py),
   drafts, gates on sourcing, records a pending approval, and — once approved —
   publishes a real content_posts-adjacent record (public_deliveries) and a
   PublishRecord.

The test that matters most is the last one: it proves the two halves above are
NOT currently wired together. run_once() enqueues a trigger; nothing consumes
that trigger into a ContentAgencyRunner call. A client with an active,
past-due content-loop pipeline gets a workflow_triggers row, not a post — the
gap is asserted explicitly here rather than left to be discovered in production.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest

from service.auctor import runner as runner_module
from service.auctor.config import Settings
from service.auctor.models import CollectorResult
from service.auctor.workflow import ClientIntake, FleetIntake, WorkflowStore
from service.tests._fake_mongo import Database


WORKSPACE = "workspace-1"
FLEET = "fleet-1"
CLIENT = "client-1"


def _store(database: Database) -> WorkflowStore:
    settings = Settings(mongodb_uri="mongodb://unused")
    return WorkflowStore(settings=settings, database=database)


def _seed_active_content_loop_pipeline(store: WorkflowStore, *, due_at: datetime) -> None:
    """A client whose site_build already shipped and whose content_loop is active and
    past-due on BOTH platforms — the exact state run_once() is meant to act on."""
    store.start_fleet(
        FleetIntake(
            workspace_id=WORKSPACE,
            fleet_id=FLEET,
            clients=[
                ClientIntake(
                    client_id=CLIENT,
                    name="Kriti Agarwal",
                    linkedin_url="https://linkedin.com/in/kriti",
                    audience=["investors"],
                )
            ],
        )
    )
    store.db.client_pipelines.update_one(
        {"workspace_id": WORKSPACE, "client_id": CLIENT, "pipeline": "content_loop"},
        {
            "$set": {
                "status": "active",
                "next_content_check_at": due_at,
                "platform_next_check": {"x": due_at, "linkedin": due_at},
            }
        },
    )


class _FakeLinkupCollector:
    """Stands in for the real network-calling LinkupCollector. Writes into the SAME
    fake Database the WorkflowStore under test reads from, so ContentAgencyRunner's
    ``memory.db.trend_items.find(...)`` sees exactly what ``.collect()`` "found"."""

    def __init__(self, database: Database, trend_doc: dict[str, Any] | None):
        self._database = database
        self._trend_doc = trend_doc

    @property
    def memory(self) -> "_FakeLinkupCollector":
        return self  # only .db is actually read off this by runner.py

    @property
    def db(self) -> Database:
        return self._database

    def collect(self, *, workspace_id: str, topics: list[str], **_: Any) -> CollectorResult:
        now = datetime.now(timezone.utc)
        if self._trend_doc:
            self._database.trend_items.update_one(
                {"workspace_id": workspace_id, "external_id": self._trend_doc["external_id"]},
                {"$setOnInsert": {"workspace_id": workspace_id, **self._trend_doc}},
                upsert=True,
            )
        return CollectorResult(
            source="linkup",
            workspace_id=workspace_id,
            raw_records=1 if self._trend_doc else 0,
            trends=1 if self._trend_doc else 0,
            started_at=now,
            completed_at=now,
        )


def _patch_linkup(database: Database, trend_doc: dict[str, Any] | None):
    return patch.object(
        runner_module, "LinkupCollector", lambda: _FakeLinkupCollector(database, trend_doc)
    )


def _sample_trend() -> dict[str, Any]:
    return {
        "external_id": "trend-1",
        "title": "Teams are shipping smaller PRs and shipping more often",
        "url": "https://example.com/smaller-prs",
        "collected_at": datetime.now(timezone.utc),
    }


# --------------------------------------------------------------------------- scheduler side


def test_enqueue_due_content_loops_creates_a_pending_trigger_per_platform():
    database = Database()
    store = _store(database)
    due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    _seed_active_content_loop_pipeline(store, due_at=due_at)

    x_triggers = store.enqueue_due_content_loops(platform="x", interval_hours=6)
    linkedin_triggers = store.enqueue_due_content_loops(platform="linkedin", interval_hours=6)

    assert len(x_triggers) == 1
    assert len(linkedin_triggers) == 1
    assert x_triggers[0]["platform"] == "x"
    assert linkedin_triggers[0]["platform"] == "linkedin"

    stored = store.db.workflow_triggers.find({"workspace_id": WORKSPACE, "client_id": CLIENT})
    assert {t["platform"] for t in stored} == {"x", "linkedin"}
    assert all(t["status"] == "pending" for t in stored)


# --------------------------------------------------------------------------- content-job side


def test_content_job_runner_researches_drafts_and_requires_approval():
    database = Database()
    store = _store(database)
    _seed_active_content_loop_pipeline(store, due_at=datetime.now(timezone.utc) + timedelta(days=7))
    agency = runner_module.ContentAgencyRunner(store=store)

    with _patch_linkup(database, _sample_trend()):
        result = agency.run_until_approval(WORKSPACE, FLEET, CLIENT, topic="shipping cadence")

    assert result["status"] == "awaiting_approval"
    assert "example.com/smaller-prs" in result["draft"]

    artifact = store.db.workflow_artifacts.find_one({"artifact_id": result["draft_id"]})
    assert artifact is not None
    assert artifact["artifact_type"] == "post_draft"
    assert artifact["source_refs"] == ["https://example.com/smaller-prs"]

    approval = store.db.approval_requests.find_one({"approval_id": result["approval_id"]})
    assert approval is not None
    assert approval["status"] == "pending"

    # Not published yet — awaiting the explicit human approval gate, same rule
    # policy.md's APPROVAL section requires for every content-loop candidate.
    assert store.db.public_deliveries.count_documents({}) == 0


def test_content_job_runner_raises_when_research_finds_nothing():
    database = Database()
    store = _store(database)
    _seed_active_content_loop_pipeline(store, due_at=datetime.now(timezone.utc) + timedelta(days=7))
    agency = runner_module.ContentAgencyRunner(store=store)

    with _patch_linkup(database, trend_doc=None):
        with pytest.raises(ValueError, match="no usable sources"):
            agency.run_until_approval(WORKSPACE, FLEET, CLIENT, topic="a very quiet week")


def test_content_job_runner_publishes_only_after_approval():
    database = Database()
    store = _store(database)
    _seed_active_content_loop_pipeline(store, due_at=datetime.now(timezone.utc) + timedelta(days=7))
    agency = runner_module.ContentAgencyRunner(store=store)

    with _patch_linkup(database, _sample_trend()):
        run = agency.run_until_approval(WORKSPACE, FLEET, CLIENT, topic="shipping cadence")

    published = agency.approve_and_publish_web(WORKSPACE, run["approval_id"])

    assert published["status"] == "published"
    delivery = store.db.public_deliveries.find_one({"post_id": published["post_id"]})
    assert delivery is not None
    assert delivery["status"] == "published"
    assert delivery["client_id"] == CLIENT

    # Publish outcomes live per-platform under platform_status.<platform> — never a
    # single top-level boolean, per policy.md's PUBLISH STATUS rule.
    publish_record = store.db.content_posts.find_one({"post_id": published["post_id"]})
    assert publish_record is not None
    assert publish_record["platform_status"]["web"]["status"] == "published"

    approval = store.db.approval_requests.find_one({"approval_id": run["approval_id"]})
    assert approval["status"] == "approved"

    # A second approval attempt on the same, already-consumed approval must fail —
    # policy.md: an approval is single-use, never reused across a regenerated draft.
    with pytest.raises(ValueError, match="pending approval not found"):
        agency.approve_and_publish_web(WORKSPACE, run["approval_id"])


# --------------------------------------------------------------------------- the actual gap


def test_a_scheduler_enqueued_trigger_is_not_automatically_turned_into_a_post():
    """The honest current-state check this test module exists for.

    A client with an active, past-due content-loop pipeline gets a
    workflow_triggers row from run_once()-equivalent enqueueing — but nothing in
    this codebase consumes that row into a ContentAgencyRunner.run_until_approval
    call. No topic is derived from real signal (GitHub/trend research per
    PRODUCT-SLICES.md Slice 3), and nothing marks the trigger non-pending. This
    assertion should start FAILING the day someone wires that consumer — flip it
    to the positive assertion at that point, don't just delete this test.
    """
    database = Database()
    store = _store(database)
    due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    _seed_active_content_loop_pipeline(store, due_at=due_at)

    triggers = store.enqueue_due_content_loops(platform="x", interval_hours=6)
    assert len(triggers) == 1

    # Nothing else runs here — this is the whole point. If a background consumer
    # existed, it would have picked up the pending trigger by now.

    still_pending = store.db.workflow_triggers.find_one({"trigger_id": triggers[0]["trigger_id"]})
    assert still_pending["status"] == "pending"

    assert store.db.workflow_artifacts.count_documents({"workspace_id": WORKSPACE}) == 0
    assert store.db.approval_requests.count_documents({"workspace_id": WORKSPACE}) == 0
    assert store.db.public_deliveries.count_documents({}) == 0
