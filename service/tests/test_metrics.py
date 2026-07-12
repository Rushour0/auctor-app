"""Unit + integration tests for the metrics/COGS unit (B-metrics-cogs).

Covers three surfaces that ship together:

* ``service.app.metrics_aggregations`` — the per-block Mongo aggregations
  (``cost_rollup``, ``cost_by_provider``, ``posts_by_status``, ``top_pipelines``) and the
  ``build_metrics_payload`` orchestrator that stitches them into one dashboard payload.
* ``service.app.routers.metrics`` — GET ``/api/metrics`` and GET ``/api/metrics/export``.
* ``service.auctor.scheduler`` — ``run_once`` and its best-effort outbound metrics push.

Mongo is faked in-process with a synchronous pymongo-shaped ``FakeDB`` (see below) rather than
mongomock, which is not a dependency of this repo; the fake implements just enough of ``find`` /
``count_documents`` / ``distinct`` / ``aggregate`` for the COGS rollups. The aggregation module is
delivered by a sibling unit, so its symbols are imported lazily *inside* each test — a missing or
renamed helper isolates to that one test instead of breaking collection of the whole file (the
endpoint + scheduler tests never touch the real aggregations and stay green regardless).
"""

from __future__ import annotations

import json
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient


# --------------------------------------------------------------------------------------------------
# In-memory pymongo-shaped fake (synchronous, matching WorkflowStore.db access patterns).
# --------------------------------------------------------------------------------------------------


def _get(document: Any, dotted: str) -> Any:
    """Read a possibly-dotted field path, returning None when any segment is absent."""
    current = document
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _exists(document: Any, dotted: str) -> bool:
    current = document
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _match(document: dict[str, Any], query: dict[str, Any] | None) -> bool:
    """Evaluate a subset of the Mongo query language (eq + $in/$nin/$ne/$exists/$gt.. + $and/$or)."""
    if not query:
        return True
    for key, cond in query.items():
        if key == "$and":
            if not all(_match(document, sub) for sub in cond):
                return False
            continue
        if key == "$or":
            if not any(_match(document, sub) for sub in cond):
                return False
            continue
        actual = _get(document, key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, expected in cond.items():
                if op == "$in" and actual not in expected:
                    return False
                if op == "$nin" and actual in expected:
                    return False
                if op == "$ne" and actual == expected:
                    return False
                if op == "$exists" and bool(expected) != _exists(document, key):
                    return False
                if op == "$gt" and not (actual is not None and actual > expected):
                    return False
                if op == "$gte" and not (actual is not None and actual >= expected):
                    return False
                if op == "$lt" and not (actual is not None and actual < expected):
                    return False
                if op == "$lte" and not (actual is not None and actual <= expected):
                    return False
        elif actual != cond:
            return False
    return True


def _sort_key(value: Any) -> tuple[int, Any]:
    # None sorts lowest; values are homogeneous within a single field for our fixtures.
    return (0, 0) if value is None else (1, value)


class _Cursor(list):
    """A list that mimics the chainable pymongo cursor surface used by the aggregations."""

    def sort(self, key: Any, direction: int = 1) -> "_Cursor":
        pairs = key if isinstance(key, list) else [(key, direction)]
        rows = list(self)
        for field, order in reversed(pairs):
            rows.sort(key=lambda row: _sort_key(_get(row, field)), reverse=order < 0)
        return _Cursor(rows)

    def limit(self, count: int) -> "_Cursor":
        return _Cursor(self[:count])

    def skip(self, count: int) -> "_Cursor":
        return _Cursor(self[count:])


def _eval(document: dict[str, Any], expr: Any) -> Any:
    """Evaluate a Mongo aggregation expression against one document."""
    if isinstance(expr, str) and expr.startswith("$"):
        return _get(document, expr[1:])
    if isinstance(expr, list):
        return [_eval(document, item) for item in expr]
    if isinstance(expr, dict) and len(expr) == 1:
        ((op, arg),) = expr.items()
        if op == "$ifNull":
            value = _eval(document, arg[0])
            return value if value is not None else _eval(document, arg[1])
        if op == "$cond":
            if isinstance(arg, list):
                condition, then, other = arg
            else:
                condition, then, other = arg["if"], arg["then"], arg["else"]
            return (
                _eval(document, then)
                if bool(_eval(document, condition))
                else _eval(document, other)
            )
        if op == "$eq":
            return _eval(document, arg[0]) == _eval(document, arg[1])
        if op == "$ne":
            return _eval(document, arg[0]) != _eval(document, arg[1])
        if op == "$literal":
            return arg
        if op == "$toDouble":
            return _num(_eval(document, arg))
        if op == "$type":
            return "missing" if _eval(document, arg) is None else "double"
        if op == "$sum":
            values = arg if isinstance(arg, list) else [arg]
            return sum(_num(_eval(document, item)) for item in values)
        if op == "$add":
            return sum(_num(_eval(document, item)) for item in arg)
        if op == "$subtract":
            return _num(_eval(document, arg[0])) - _num(_eval(document, arg[1]))
        if op == "$multiply":
            result = 1.0
            for item in arg:
                result *= _num(_eval(document, item))
            return result
        if op == "$divide":
            denom = _num(_eval(document, arg[1]))
            return _num(_eval(document, arg[0])) / denom if denom else None
    if isinstance(expr, dict):
        return {key: _eval(document, value) for key, value in expr.items()}
    return expr


def _freeze(value: Any) -> Any:
    try:
        hash(value)
        return value
    except TypeError:
        return repr(value)


def _group(documents: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    buckets: "OrderedDict[Any, list[Any]]" = OrderedDict()
    for document in documents:
        identity = _eval(document, spec["_id"])
        key = _freeze(identity)
        if key not in buckets:
            buckets[key] = [identity, []]
        buckets[key][1].append(document)
    output: list[dict[str, Any]] = []
    for identity, rows in buckets.values():
        row: dict[str, Any] = {"_id": identity}
        for field, accumulator in spec.items():
            if field == "_id":
                continue
            ((op, expr),) = accumulator.items()
            values = [_eval(doc, expr) for doc in rows]
            if op == "$sum":
                row[field] = sum(_num(value) for value in values)
            elif op == "$max":
                present = [v for v in values if v is not None]
                row[field] = max(present) if present else None
            elif op == "$min":
                present = [v for v in values if v is not None]
                row[field] = min(present) if present else None
            elif op == "$first":
                row[field] = values[0] if values else None
            elif op == "$last":
                row[field] = values[-1] if values else None
            elif op == "$avg":
                present = [_num(v) for v in values if v is not None]
                row[field] = sum(present) / len(present) if present else None
            elif op == "$push":
                row[field] = values
            elif op == "$addToSet":
                unique: list[Any] = []
                for value in values:
                    if value not in unique:
                        unique.append(value)
                row[field] = unique
            else:
                row[field] = None
        output.append(row)
    return output


class FakeCollection:
    """Synchronous, pymongo-shaped collection backed by a plain list of documents."""

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    def create_index(self, *_: Any, **__: Any) -> None:
        return None

    def insert_one(self, document: dict[str, Any]) -> None:
        self.documents.append(deepcopy(document))

    def insert_many(self, documents: list[dict[str, Any]]) -> None:
        self.documents.extend(deepcopy(document) for document in documents)

    def count_documents(self, query: dict[str, Any] | None = None) -> int:
        return sum(_match(document, query) for document in self.documents)

    def find(
        self, query: dict[str, Any] | None = None, projection: dict[str, int] | None = None
    ) -> _Cursor:
        return _Cursor(deepcopy(row) for row in self.documents if _match(row, query))

    def find_one(
        self, query: dict[str, Any] | None = None, projection: dict[str, int] | None = None
    ) -> dict[str, Any] | None:
        for document in self.documents:
            if _match(document, query):
                return deepcopy(document)
        return None

    def distinct(self, key: str, query: dict[str, Any] | None = None) -> list[Any]:
        seen: list[Any] = []
        for document in self.documents:
            if _match(document, query):
                value = _get(document, key)
                if value is not None and value not in seen:
                    seen.append(value)
        return seen

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [deepcopy(document) for document in self.documents]
        for stage in pipeline:
            ((op, spec),) = stage.items()
            if op == "$match":
                rows = [row for row in rows if _match(row, spec)]
            elif op == "$group":
                rows = _group(rows, spec)
            elif op == "$sort":
                for field, order in reversed(list(spec.items())):
                    rows.sort(key=lambda row: _sort_key(_get(row, field)), reverse=order < 0)
            elif op == "$limit":
                rows = rows[:spec]
            elif op == "$skip":
                rows = rows[spec:]
            elif op == "$count":
                rows = [{spec: len(rows)}]
            elif op == "$project":
                rows = [{key: _eval(row, value) for key, value in spec.items()} for row in rows]
        return rows


class FakeDB:
    """Returns a lazily-created FakeCollection per attribute, mirroring a pymongo Database."""

    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getattr__(self, name: str) -> FakeCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._collections.setdefault(name, FakeCollection())


# --------------------------------------------------------------------------------------------------
# Tolerant accessors — the sibling aggregation module owns exact key/return-shape naming, so read
# the semantic value through a small set of candidate keys instead of hard-coding one spelling.
# --------------------------------------------------------------------------------------------------

WS = "ws1"


def _first_present(mapping: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    for candidate in candidates:
        if candidate in mapping:
            return mapping[candidate]
    return None


def _cost_of(row: dict[str, Any]) -> float:
    return _num(_first_present(row, ("cost_usd", "total_usd", "cost", "usd", "spend_usd")))


def _label_of(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    return _first_present(row, keys)


def _as_histogram(result: Any) -> dict[str, int]:
    """Normalise a status histogram returned as either a dict or a list of rows."""
    if isinstance(result, dict):
        return {str(k): int(v) for k, v in result.items()}
    histogram: dict[str, int] = {}
    for row in result:
        label = _label_of(row, ("status", "_id", "name", "label"))
        count = _first_present(row, ("count", "n", "total", "value"))
        if label is not None:
            histogram[str(label)] = int(count or 0)
    return histogram


def _as_provider_costs(result: Any) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for row in result:
        provider = _label_of(row, ("provider", "_id", "name", "label"))
        mapping[str(provider)] = _cost_of(row)
    return mapping


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------------------------------
# Seed helpers.
# --------------------------------------------------------------------------------------------------


def _pipeline_doc(client_id: str, status: str, cost: float, pipeline: str = "content_loop") -> dict:
    return {
        "workspace_id": WS,
        "fleet_id": "fleet-1",
        "client_id": client_id,
        "pipeline": pipeline,
        "status": status,
        "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": cost},
    }


def _event_doc(provider: Any, cost: float, include_provider: bool = True) -> dict:
    payload: dict[str, Any] = {"cost_usd": cost}
    if include_provider:
        payload["provider"] = provider
    return {
        "workspace_id": WS,
        "fleet_id": "fleet-1",
        "event_type": "usage_recorded",
        "payload": payload,
    }


def _post_doc(post_id: str, platform_statuses: dict[str, str], status: str | None = None) -> dict:
    """Seed one content_posts doc.

    ``platform_statuses`` maps each *present* platform to its per-platform status sub-doc; the
    post-level ``status`` (what ``posts_by_status`` / ``cost_rollup`` actually count) defaults to
    the x value, then the first present platform, unless overridden explicitly.
    """
    platform_status = {
        platform: {"platform": platform, "status": value}
        for platform, value in platform_statuses.items()
    }
    top_status = status or platform_statuses.get("x") or next(iter(platform_statuses.values()))
    return {
        "workspace_id": WS,
        "fleet_id": "fleet-1",
        "client_id": "client-1",
        "post_id": post_id,
        "status": top_status,
        "platform_status": platform_status,
    }


# --------------------------------------------------------------------------------------------------
# (1) cost_rollup — total spend must include failed/cancelled runs, not just active ones.
# --------------------------------------------------------------------------------------------------


def test_cost_rollup_surfaces_failed_spend() -> None:
    from service.app.metrics_aggregations import cost_rollup

    db = FakeDB()
    db.client_pipelines.insert_many(
        [
            _pipeline_doc("client-1", "active", 2.0),
            _pipeline_doc("client-2", "active", 1.0),
            _pipeline_doc("client-3", "failed", 1.0),
            _pipeline_doc("client-4", "cancelled", 0.5),
        ]
    )
    # Two published posts (+ one still drafting) → avg divides by the published count only.
    db.content_posts.insert_many(
        [
            _post_doc("post-1", {"x": "published"}),
            _post_doc("post-2", {"x": "published"}),
            _post_doc("post-3", {"x": "drafting"}),
        ]
    )

    rollup = cost_rollup(db, WS)

    total = _num(_first_present(rollup, ("total_usd", "total", "cost_usd")))
    failed = _num(_first_present(rollup, ("failed_usd", "failed", "failed_cost_usd")))
    avg = _num(_first_present(rollup, ("avg_per_post_usd", "avg_per_post", "average_per_post_usd")))

    # Total rolls up every pipeline's spend, so it strictly exceeds the active-only 3.0.
    assert total == pytest.approx(4.5)
    assert total > 3.0
    # Failed spend is the failed + cancelled sum, surfaced separately.
    assert failed == pytest.approx(1.5)
    # Average divides total spend by the two *published* posts.
    assert avg == pytest.approx(4.5 / 2)


# --------------------------------------------------------------------------------------------------
# (2) cost_by_provider — group fleet_events by payload.provider, missing provider → 'unknown'.
# --------------------------------------------------------------------------------------------------


def test_cost_by_provider_groups_events() -> None:
    from service.app.metrics_aggregations import cost_by_provider

    db = FakeDB()
    db.fleet_events.insert_many(
        [
            _event_doc("anthropic", 1.0),
            _event_doc("anthropic", 2.0),
            _event_doc("openai", 0.5),
            _event_doc(None, 0.25, include_provider=False),
        ]
    )

    result = cost_by_provider(db, WS)

    assert isinstance(result, list)
    costs = _as_provider_costs(result)
    assert costs["anthropic"] == pytest.approx(3.0)
    assert costs["openai"] == pytest.approx(0.5)
    # An event whose payload carries no provider is bucketed under 'unknown', never dropped.
    assert costs["unknown"] == pytest.approx(0.25)
    # The list is returned pre-sorted by spend (descending).
    ordered = [_cost_of(row) for row in result]
    assert ordered == sorted(ordered, reverse=True)


# --------------------------------------------------------------------------------------------------
# (3) posts_by_status — per-platform drill-down (platform_status.x is independent of .linkedin).
# --------------------------------------------------------------------------------------------------


def test_posts_by_status_platform_drilldown() -> None:
    from service.app.metrics_aggregations import posts_by_status

    db = FakeDB()
    # The drill-down keys off which platform each post was published to (platform_status.<p>
    # existing), then counts the post-level status — so X and LinkedIn scope to different post
    # sets. post-2 is X-only; post-3 is LinkedIn-only.
    db.content_posts.insert_many(
        [
            _post_doc("post-1", {"x": "published", "linkedin": "published"}, status="published"),
            _post_doc("post-2", {"x": "published"}, status="published"),
            _post_doc("post-3", {"linkedin": "failed"}, status="failed"),
        ]
    )

    x_histogram = _as_histogram(posts_by_status(db, WS, "x"))
    linkedin_histogram = _as_histogram(posts_by_status(db, WS, "linkedin"))

    # X tab → posts published to X (post-1, post-2): both published, and the LinkedIn-only
    # failure never leaks in. This is a per-platform narrowing, not a single post-level boolean.
    assert x_histogram.get("published") == 2
    assert x_histogram.get("failed") is None
    # LinkedIn tab → posts published to LinkedIn (post-1, post-3): one published, one failed.
    assert linkedin_histogram.get("published") == 1
    assert linkedin_histogram.get("failed") == 1
    # The two platforms scope to different post sets → the drill-down is genuinely per-platform.
    assert x_histogram != linkedin_histogram


# --------------------------------------------------------------------------------------------------
# (4) top_pipelines — ranked by spend, descending, capped at five.
# --------------------------------------------------------------------------------------------------


def test_top_pipelines_ranked_by_cost() -> None:
    from service.app.metrics_aggregations import top_pipelines

    db = FakeDB()
    db.client_pipelines.insert_many(
        [_pipeline_doc(f"client-{i}", "active", float(i)) for i in range(1, 7)]
    )

    ranked = top_pipelines(db, WS)

    assert isinstance(ranked, list)
    # Six pipelines seeded, only the top five surface.
    assert len(ranked) == 5
    costs = [_cost_of(row) for row in ranked]
    assert costs == sorted(costs, reverse=True)
    # The cheapest pipeline (cost 1.0) is dropped off the bottom of the ranking.
    assert 1.0 not in costs
    assert costs[0] == pytest.approx(6.0)


# --------------------------------------------------------------------------------------------------
# (5) build_metrics_payload — assembled shape, fixed platform set, ISO timestamp.
# --------------------------------------------------------------------------------------------------


def test_build_metrics_payload_shape() -> None:
    from service.app.metrics_aggregations import build_metrics_payload

    db = FakeDB()
    db.client_pipelines.insert_many(
        [_pipeline_doc("client-1", "active", 2.0), _pipeline_doc("client-2", "failed", 1.0)]
    )
    db.content_posts.insert_one(_post_doc("post-1", {"x": "published"}))
    db.fleet_events.insert_one(_event_doc("anthropic", 1.0))

    payload = build_metrics_payload(db, WS)

    assert isinstance(payload, dict)
    # The platform set is fixed to exactly X + LinkedIn (the two supported channels).
    assert payload["available_platforms"] == ["x", "linkedin"]
    # generated_at is an ISO-8601 string that round-trips through datetime.fromisoformat.
    assert isinstance(payload["generated_at"], str)
    assert isinstance(datetime.fromisoformat(payload["generated_at"]), datetime)
    # Each COGS block is present under one of its expected names.
    assert any(k in payload for k in ("cost_rollup", "cost", "cogs"))
    assert any(k in payload for k in ("cost_by_provider", "provider_costs"))
    assert any(k in payload for k in ("posts_by_status", "post_status"))
    assert any(k in payload for k in ("top_pipelines", "top_spenders", "top_projects"))


# --------------------------------------------------------------------------------------------------
# (6) HTTP endpoints — /api/metrics and /api/metrics/export (ASGI transport + lifespan).
# --------------------------------------------------------------------------------------------------


CANNED_PAYLOAD = {
    "workspace_id": WS,
    "available_platforms": ["x", "linkedin"],
    "generated_at": "2026-07-12T00:00:00+00:00",
    "cost_rollup": {"total_usd": 4.5, "failed_usd": 1.5, "avg_per_post_usd": 2.25},
    "cost_by_provider": [{"provider": "anthropic", "cost_usd": 3.0}],
    "posts_by_status": {"published": 2},
    "top_pipelines": [{"client_id": "client-1", "cost_usd": 6.0}],
}


async def test_metrics_endpoint_200(monkeypatch) -> None:
    import service.app.routers.metrics as metrics_route
    from service.app.main import app

    # Neither the real WorkflowStore (which would hit Mongo on ensure_indexes) nor the real
    # aggregations are exercised here — the router wiring + envelope are what's under test.
    monkeypatch.setattr(metrics_route, "_workflow_store", lambda: SimpleNamespace(db=object()))
    monkeypatch.setattr(
        metrics_route,
        "build_metrics_payload",
        lambda db, workspace_id, platform=None: CANNED_PAYLOAD,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            metrics = await client.get("/api/metrics", params={"workspace_id": WS})
            export = await client.get("/api/metrics/export", params={"workspace_id": WS})

    assert metrics.status_code == 200
    body = metrics.json()
    assert body["available_platforms"] == ["x", "linkedin"]
    assert "generated_at" in body
    assert "cost_rollup" in body

    assert export.status_code == 200
    envelope = export.json()
    assert envelope["schema"] == "auctor.metrics.v1"
    assert envelope["payload"] == CANNED_PAYLOAD


# --------------------------------------------------------------------------------------------------
# (7) scheduler push — disabled (no webhook URL) makes zero outbound calls.
# --------------------------------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, settings: Any = None) -> None:
        self.settings = settings
        self.db = SimpleNamespace()

    def ensure_indexes(self) -> None:
        return None

    def enqueue_due_content_loops(
        self, platform: Any = None, interval_hours: Any = None, batch_size: Any = None
    ) -> list[dict[str, Any]]:
        return []


def _settings(webhook_url: str) -> Any:
    from service.auctor.config import Settings

    return Settings(
        mongodb_uri="mongodb://unused",
        metrics_webhook_url=webhook_url,
        auctor_workspace_id=WS,
    )


def test_scheduler_push_disabled_when_no_url(monkeypatch) -> None:
    from service.auctor import scheduler

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("httpx.post must not be called when metrics_webhook_url is unset")

    monkeypatch.setattr(scheduler, "WorkflowStore", _FakeStore)
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings(""))
    monkeypatch.setattr(scheduler.httpx, "post", _explode)

    result = scheduler.run_once()

    assert result["pushed"] is False
    assert result["enqueued"] == 0
    assert result["by_platform"] == {"x": 0, "linkedin": 0}


# --------------------------------------------------------------------------------------------------
# (8) scheduler push — enabled posts the versioned envelope; a transport error is swallowed.
# --------------------------------------------------------------------------------------------------


def test_scheduler_push_posts_envelope(monkeypatch) -> None:
    from service.auctor import scheduler
    import service.app.metrics_aggregations as aggregations

    monkeypatch.setattr(scheduler, "WorkflowStore", _FakeStore)
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings("https://hook.example/push"))
    monkeypatch.setattr(
        aggregations,
        "build_metrics_payload",
        lambda db, workspace_id, platform=None: {"total_usd": 4.5},
    )

    captured: dict[str, Any] = {}

    def _capture(url: str, *args: Any, content: Any = None, headers: Any = None, **kwargs: Any):
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers or {}
        return SimpleNamespace(is_success=True)

    monkeypatch.setattr(scheduler.httpx, "post", _capture)

    result = scheduler.run_once()

    assert result["pushed"] is True
    assert captured["headers"].get("content-type") == "application/json"
    body = json.loads(captured["content"])
    assert body["schema"] == "auctor.metrics.v1"
    assert body["source"] == "scheduler"
    assert body["payload"] == {"total_usd": 4.5}

    # A transport failure must degrade to pushed=False without propagating out of run_once.
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise scheduler.httpx.HTTPError("connection refused")

    monkeypatch.setattr(scheduler.httpx, "post", _raise)
    degraded = scheduler.run_once()
    assert degraded["pushed"] is False
