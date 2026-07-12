import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from service.app.conversations import (
    EVENT_MESSAGE_MAP,
    MESSAGE_TYPES,
    _iso,
    _role_for,
    summarize_event,
    to_sse,
)
from service.app.main import app


def test_message_map_only_emits_valid_contract_types():
    for message_type, _default in EVENT_MESSAGE_MAP.values():
        assert message_type in MESSAGE_TYPES


def test_message_types_has_exactly_eight():
    assert len(MESSAGE_TYPES) == 8


def test_role_for():
    assert _role_for("user_message") == "user"
    assert _role_for("assistant_message") == "assistant"
    assert _role_for("progress") == "assistant"
    assert _role_for("run_failed") == "assistant"


def test_iso_is_null_safe():
    assert _iso(None) is None
    assert _iso("2026-07-12T00:00:00+00:00") == "2026-07-12T00:00:00+00:00"
    dt = datetime(2026, 7, 12, tzinfo=timezone.utc)
    assert _iso(dt) == dt.isoformat()


def test_summarize_known_event_uses_default_text():
    msg = summarize_event(
        {
            "event_type": "run_completed",
            "idempotency_key": "run:abc",
            "client_id": "client_1",
            "pipeline": "onboarding",
            "recorded_at": datetime(2026, 7, 12, tzinfo=timezone.utc),
        }
    )
    assert msg["id"] == "run:abc"
    assert msg["message_type"] == "run_completed"
    assert msg["role"] == "assistant"
    assert msg["text"] == "Completed. Artifacts are ready."
    assert msg["client_id"] == "client_1"
    assert msg["pipeline"] == "onboarding"
    assert msg["recorded_at"] == "2026-07-12T00:00:00+00:00"


def test_summarize_payload_summary_overrides_default_text():
    msg = summarize_event(
        {
            "event_type": "approval_requested",
            "idempotency_key": "appr:1",
            "payload": {"summary": "Approve the launch post?"},
        }
    )
    assert msg["message_type"] == "approval_request"
    assert msg["text"] == "Approve the launch post?"


def test_summarize_payload_text_used_when_no_summary():
    msg = summarize_event(
        {
            "event_type": "assistant_message",
            "event_id": "event_xyz",
            "payload": {"text": "Here is your draft."},
        }
    )
    assert msg["message_type"] == "assistant_message"
    assert msg["text"] == "Here is your draft."
    assert msg["id"] == "event_xyz"


def test_summarize_unknown_event_status_failed_refines_to_run_failed():
    msg = summarize_event({"event_type": "mystery_boom", "payload": {"status": "failed"}})
    assert msg["message_type"] == "run_failed"
    assert msg["text"] == "A run failed and needs attention."


def test_summarize_unknown_event_status_completed_refines_to_run_completed():
    msg = summarize_event({"event_type": "mystery_done", "payload": {"status": "completed"}})
    assert msg["message_type"] == "run_completed"


def test_summarize_stage_blocked_with_approval_id_maps_to_approval_request():
    """Regression test: ContentAgencyRunner records its approval-gate step as
    event_type "stage.blocked" (the generic f"stage.{outcome}" every stage uses),
    which never matches EVENT_MESSAGE_MAP by name. Without the outcome+approval_id
    override, this — the actual shape every real content-loop run produces — would
    render as a generic 'progress' message and the Conversations page's Approve
    button would never appear."""
    msg = summarize_event(
        {
            "event_type": "stage.blocked",
            "outcome": "blocked",
            "idempotency_key": "run_1:approval:1:blocked",
            "payload": {"approval_id": "approval_1", "artifact_id": "draft_1"},
        }
    )
    assert msg["message_type"] == "approval_request"
    assert msg["text"] == "Approval is needed before publishing."


def test_summarize_blocked_without_approval_id_does_not_become_approval_request():
    """A blocked stage with no approval_id in payload (some other kind of block)
    must not be misclassified — the override is scoped to the real signal."""
    msg = summarize_event(
        {"event_type": "stage.blocked", "outcome": "blocked", "payload": {"reason": "rate_limited"}}
    )
    assert msg["message_type"] == "progress"


def test_summarize_unknown_event_falls_back_to_progress_with_event_type_text():
    msg = summarize_event({"event_type": "custom_step", "idempotency_key": "k1"})
    assert msg["message_type"] == "progress"
    assert msg["text"] == "custom_step"
    assert msg["role"] == "assistant"


def test_summarize_id_falls_back_to_recorded_at_iso():
    msg = summarize_event(
        {"event_type": "run_started", "recorded_at": datetime(2026, 7, 12, tzinfo=timezone.utc)}
    )
    assert msg["id"] == "2026-07-12T00:00:00+00:00"


def test_user_message_role_is_user():
    msg = summarize_event(
        {"event_type": "user_message", "idempotency_key": "u1", "payload": {"text": "Hi"}}
    )
    assert msg["role"] == "user"
    assert msg["message_type"] == "user_message"


def test_to_sse_frames_record():
    msg = summarize_event(
        {"event_type": "run_completed", "idempotency_key": "run:abc", "payload": {}}
    )
    frame = to_sse(msg)
    assert frame.startswith("id: run:abc\n")
    assert "event: run_completed\n" in frame
    assert frame.endswith("\n\n")
    data_line = [line for line in frame.splitlines() if line.startswith("data: ")][0]
    parsed = json.loads(data_line[len("data: ") :])
    assert parsed["message_type"] == "run_completed"
    assert parsed["id"] == "run:abc"


def test_summarize_content_loop_scheduled_maps_to_progress_with_default_text():
    msg = summarize_event(
        {"event_type": "content_loop_scheduled", "idempotency_key": "loop:1", "payload": {}}
    )
    assert msg["message_type"] == "progress"
    assert msg["id"] == "loop:1"
    assert msg["text"].strip()


def test_every_summarized_message_type_is_a_valid_contract_type():
    samples = [
        {"event_type": et, "payload": {}}
        for et in list(EVENT_MESSAGE_MAP) + ["unknown_a", "unknown_b"]
    ]
    samples.append({"event_type": "generic", "payload": {"status": "failed"}})
    samples.append({"event_type": "generic", "payload": {"status": "completed"}})
    for event in samples:
        assert summarize_event(event)["message_type"] in MESSAGE_TYPES


def test_to_sse_contains_the_three_sse_fields_and_blank_line():
    frame = to_sse(summarize_event({"event_type": "run_started", "idempotency_key": "s1"}))
    assert "event: " in frame
    assert "data: " in frame
    assert "id: " in frame
    assert frame.endswith("\n\n")


# --------------------------------------------------------------------------------------------------
# In-file async Mongo fake (no mongomock in this repo)
# --------------------------------------------------------------------------------------------------
def _matches(doc: dict, query: dict) -> bool:
    """Faithful-enough subset of Mongo query matching: equality plus the operators the routers use."""
    for key, expected in query.items():
        actual = doc.get(key)
        if isinstance(expected, dict) and any(k.startswith("$") for k in expected):
            for op, operand in expected.items():
                if op == "$gt" and not (actual is not None and actual > operand):
                    return False
                if op == "$gte" and not (actual is not None and actual >= operand):
                    return False
                if op == "$lt" and not (actual is not None and actual < operand):
                    return False
                if op == "$lte" and not (actual is not None and actual <= operand):
                    return False
                if op == "$ne" and actual == operand:
                    return False
                if op == "$in" and actual not in operand:
                    return False
                if op == "$exists" and (key in doc) != bool(operand):
                    return False
        elif actual != expected:
            return False
    return True


class FakeCursor:
    """Chainable cursor mirroring motor's ``find(...).sort(...).skip(...).limit(...).to_list(n)``."""

    def __init__(self, docs: list[dict]):
        self._docs = list(docs)

    def sort(self, field, direction: int = 1) -> "FakeCursor":
        # Accept both sort("recorded_at", -1) and sort([("recorded_at", -1)]) call shapes.
        keys = field if isinstance(field, (list, tuple)) else [(field, direction)]
        for spec_field, spec_dir in reversed(keys):
            self._docs.sort(key=lambda d: d.get(spec_field), reverse=spec_dir < 0)
        return self

    def skip(self, n: int) -> "FakeCursor":
        self._docs = self._docs[n:]
        return self

    def limit(self, n: int) -> "FakeCursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs if length is None else self._docs[:length]


class FakeAsyncCollection:
    """Async Mongo collection double backed by a plain in-memory list of docs."""

    def __init__(self, docs: list[dict] | None = None):
        self._docs = list(docs or [])

    def _project(self, doc: dict, projection: dict | None) -> dict:
        # Only the ``{"_id": 0}`` exclusion the routers use matters; seed docs carry no ``_id``.
        out = dict(doc)
        if projection:
            for key, keep in projection.items():
                if keep == 0:
                    out.pop(key, None)
        return out

    def find(self, query: dict | None = None, projection: dict | None = None) -> FakeCursor:
        matched = [self._project(d, projection) for d in self._docs if _matches(d, query or {})]
        return FakeCursor(matched)

    async def find_one(self, query: dict | None = None, projection: dict | None = None):
        for doc in self._docs:
            if _matches(doc, query or {}):
                return self._project(doc, projection)
        return None

    async def count_documents(self, query: dict | None = None) -> int:
        return sum(1 for d in self._docs if _matches(d, query or {}))


class FakeAsyncDB:
    """Exposes exactly the two collections the conversations router reads."""

    def __init__(self, fleet_runs: list[dict], fleet_events: list[dict]):
        self.fleet_runs = FakeAsyncCollection(fleet_runs)
        self.fleet_events = FakeAsyncCollection(fleet_events)


_CREATED_AT = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
_EVENT_A_AT = datetime(2026, 7, 11, 9, 0, 0, tzinfo=timezone.utc)
_EVENT_B_AT = datetime(2026, 7, 11, 10, 0, 0, tzinfo=timezone.utc)


def _seed_db() -> FakeAsyncDB:
    """One active fleet (``fleet_x``) + two ascending-in-time events for it."""
    fleet_runs = [
        {
            "fleet_id": "fleet_x",
            "workspace_id": "ws1",
            "status": "active",
            "request": "r",
            "created_at": _CREATED_AT,
            "updated_at": _EVENT_B_AT,
        }
    ]
    fleet_events = [
        {
            "workspace_id": "ws1",
            "fleet_id": "fleet_x",
            "event_type": "content_loop_scheduled",
            "idempotency_key": "evt_a",
            "payload": {},
            "recorded_at": _EVENT_A_AT,
        },
        {
            "workspace_id": "ws1",
            "fleet_id": "fleet_x",
            "event_type": "run_completed",
            "idempotency_key": "evt_b",
            "payload": {"summary": "All done."},
            "recorded_at": _EVENT_B_AT,
        },
    ]
    return FakeAsyncDB(fleet_runs, fleet_events)


def _msg_key(item: dict) -> str | None:
    """Identity of a fetched item whether ``_fetch_since`` returns raw events or summarized messages."""
    return item.get("id") or item.get("idempotency_key")


# --------------------------------------------------------------------------------------------------
# Part 2 - route tests over the real ASGI app with a fake db injected post-lifespan
# --------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_conversations_returns_fleet_with_message_count_and_last_message():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            app.state.db = _seed_db()
            resp = await client.get("/api/conversations")

    assert resp.status_code == 200
    conversations = resp.json()["conversations"]
    assert conversations[0]["fleet_id"] == "fleet_x"
    assert conversations[0]["message_count"] == 2
    assert isinstance(conversations[0]["last_message"], dict)


@pytest.mark.asyncio
async def test_get_conversation_returns_fleet_and_two_messages():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            app.state.db = _seed_db()
            resp = await client.get("/api/conversations/fleet_x")

    assert resp.status_code == 200
    body = resp.json()
    assert body["fleet"]["fleet_id"] == "fleet_x"
    assert len(body["messages"]) == 2


@pytest.mark.asyncio
async def test_get_conversation_missing_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            app.state.db = _seed_db()
            resp = await client.get("/api/conversations/missing")

    assert resp.status_code == 404


# --------------------------------------------------------------------------------------------------
# Part 3 - the extracted SSE-polling core, exercised without running the streaming generator
# --------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fetch_since_without_cursor_returns_all_events_ascending():
    from service.app.routers.conversations import _fetch_since

    fake = _seed_db()
    events = await _fetch_since(fake, "fleet_x", after_dt=None)
    assert [_msg_key(e) for e in events] == ["evt_a", "evt_b"]


@pytest.mark.asyncio
async def test_fetch_since_with_cursor_returns_only_newer_events():
    from service.app.routers.conversations import _fetch_since

    fake = _seed_db()
    events = await _fetch_since(fake, "fleet_x", after_dt=_EVENT_A_AT)
    assert [_msg_key(e) for e in events] == ["evt_b"]
