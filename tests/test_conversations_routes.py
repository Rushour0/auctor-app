"""Exercises the /api/conversations router + its SSE helpers against fake async collections.

No real Mongo in CI, so we stand in tiny in-memory async doubles that mirror the motor surface the
router uses (count_documents / find -> sortable cursor / find_one) and swap them onto app.state.db
after the lifespan opens its real client. The stream helpers (_parse_cursor / _fetch_since /
_event_stream) are unit-tested directly so we never have to drive a live long-poll to timeout.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from service.app.main import app
from service.app.routers.conversations import (
    _event_stream,
    _fetch_since,
    _parse_cursor,
)


class _FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, key: str, direction: int) -> "_FakeCursor":
        self._docs = sorted(self._docs, key=lambda d: d.get(key), reverse=direction < 0)
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        return list(self._docs[:length] if length is not None else self._docs)


def _matches(doc: dict, query: dict) -> bool:
    for key, expected in query.items():
        value = doc.get(key)
        if isinstance(expected, dict) and "$gt" in expected:
            if value is None or not value > expected["$gt"]:
                return False
        elif value != expected:
            return False
    return True


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def _filter(self, query: dict) -> list[dict]:
        return [d for d in self._docs if _matches(d, query)]

    async def count_documents(self, query: dict) -> int:
        return len(self._filter(query))

    def find(self, query: dict, projection: dict | None = None) -> _FakeCursor:
        matched = self._filter(query)
        if projection:
            drop = {k for k, v in projection.items() if v == 0}
            matched = [{k: v for k, v in d.items() if k not in drop} for d in matched]
        return _FakeCursor(matched)

    async def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        for doc in self._filter(query):
            if projection:
                drop = {k for k, v in projection.items() if v == 0}
                return {k: v for k, v in doc.items() if k not in drop}
            return dict(doc)
        return None


class _FakeDB:
    def __init__(self, fleet_runs: list[dict], fleet_events: list[dict]):
        self.fleet_runs = _FakeCollection(fleet_runs)
        self.fleet_events = _FakeCollection(fleet_events)


def _dt(day: int) -> datetime:
    return datetime(2026, 7, day, tzinfo=timezone.utc)


def _sample_fleets() -> list[dict]:
    return [
        {
            "fleet_id": "fleet_1",
            "workspace_id": "ws_1",
            "status": "active",
            "request": "grow the X account",
            "created_at": _dt(9),
            "updated_at": _dt(10),
        },
        {
            "fleet_id": "fleet_2",
            "workspace_id": "ws_2",
            "status": "completed",
            "request": "ship a launch thread",
            "created_at": _dt(10),
            "updated_at": _dt(12),
        },
    ]


def _sample_events() -> list[dict]:
    return [
        {
            "fleet_id": "fleet_1",
            "event_id": "evt_1",
            "event_type": "run_started",
            "recorded_at": _dt(9),
            "payload": {},
        },
        {
            "fleet_id": "fleet_1",
            "event_id": "evt_2",
            "event_type": "run_completed",
            "recorded_at": _dt(10),
            "payload": {"summary": "All done."},
        },
        {
            "fleet_id": "fleet_2",
            "event_id": "evt_3",
            "event_type": "run_failed",
            "recorded_at": _dt(12),
            "payload": {"summary": "Boom."},
        },
    ]


@pytest.fixture
def fake_client():
    async def _run(path="/api/conversations", params=None, headers=None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with app.router.lifespan_context(app):
                app.state.db = _FakeDB(_sample_fleets(), _sample_events())
                return await client.get(path, params=params, headers=headers)

    return _run


# ---- list ---------------------------------------------------------------------------------------


async def test_list_returns_rows_newest_first_with_counts_and_last_message(fake_client):
    resp = await fake_client()
    assert resp.status_code == 200
    body = resp.json()
    rows = body["conversations"]
    assert [r["fleet_id"] for r in rows] == ["fleet_2", "fleet_1"]

    fleet_1 = next(r for r in rows if r["fleet_id"] == "fleet_1")
    assert fleet_1["message_count"] == 2
    # Newest event on fleet_1 is the completion.
    assert fleet_1["last_message"]["message_type"] == "run_completed"
    assert fleet_1["last_message"]["text"] == "All done."
    assert fleet_1["request"] == "grow the X account"
    assert fleet_1["created_at"] == _dt(9).isoformat()


async def test_list_filters_by_workspace(fake_client):
    resp = await fake_client(params={"workspace_id": "ws_2"})
    rows = resp.json()["conversations"]
    assert [r["fleet_id"] for r in rows] == ["fleet_2"]
    assert rows[0]["last_message"]["message_type"] == "run_failed"


# ---- detail -------------------------------------------------------------------------------------


async def test_detail_returns_fleet_and_ordered_messages(fake_client):
    resp = await fake_client(path="/api/conversations/fleet_1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fleet"]["fleet_id"] == "fleet_1"
    assert "_id" not in body["fleet"]
    assert body["message_count"] == 2
    types = [m["message_type"] for m in body["messages"]]
    assert types == ["progress", "run_completed"]


async def test_detail_404_when_missing(fake_client):
    resp = await fake_client(path="/api/conversations/fleet_nope")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "conversation not found"


# ---- events (SSE) -------------------------------------------------------------------------------


async def test_events_404_when_fleet_missing(fake_client):
    resp = await fake_client(path="/api/conversations/fleet_nope/events")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "conversation not found"


# ---- helpers ------------------------------------------------------------------------------------


def test_parse_cursor_handles_iso_z_naive_and_none():
    assert _parse_cursor(None) is None
    assert _parse_cursor("") is None
    assert _parse_cursor("not-a-date") is None
    z = _parse_cursor("2026-07-10T00:00:00Z")
    assert z == _dt(10)
    naive = _parse_cursor("2026-07-10T00:00:00")
    assert naive.tzinfo is timezone.utc
    assert _parse_cursor(_dt(9)) == _dt(9)


async def test_fetch_since_filters_and_orders():
    db = _FakeDB(_sample_fleets(), _sample_events())
    all_events = await _fetch_since(db, "fleet_1", None)
    assert [e["event_id"] for e in all_events] == ["evt_1", "evt_2"]

    after = await _fetch_since(db, "fleet_1", _dt(9))
    assert [e["event_id"] for e in after] == ["evt_2"]

    none_left = await _fetch_since(db, "fleet_1", _dt(10))
    assert none_left == []


class _FakeRequest:
    """Minimal Request double: reports disconnected after the first drain pass."""

    def __init__(self):
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return True


async def test_event_stream_emits_frames_then_stops_on_disconnect():
    db = _FakeDB(_sample_fleets(), _sample_events())
    frames = [frame async for frame in _event_stream(_FakeRequest(), db, "fleet_1", None)]
    # Two events -> two SSE data frames, then the disconnect check ends the loop.
    assert sum(1 for f in frames if f.startswith("id: ")) == 2
    assert "event: run_completed" in "".join(frames)


async def test_event_stream_heartbeat_when_no_new_events():
    db = _FakeDB(_sample_fleets(), _sample_events())
    frames = [frame async for frame in _event_stream(_FakeRequest(), db, "fleet_1", _dt(10))]
    assert frames == [": keepalive\n\n"]
