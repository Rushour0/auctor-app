from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from service.auctor import scheduler
from service.auctor.config import Settings
from service.auctor.workflow import ClientIntake, FleetIntake, WorkflowStore


# Minimal in-memory Mongo double, mirroring service/tests/test_workflow_persistence.py's harness
# (service/tests has no __init__.py, so it cannot be imported as a package).
def nested_set(document: dict[str, Any], path: str, value: Any) -> None:
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = document.get(key)
        if "." in key:
            actual = document
            for part in key.split("."):
                actual = actual.get(part) if isinstance(actual, dict) else None
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
        def value(row: dict[str, Any]) -> Any:
            target: Any = row
            for part in key.split("."):
                target = target.get(part) if isinstance(target, dict) else None
            return target

        return Cursor(sorted(self, key=value, reverse=direction < 0))


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


def _seeded_store(due: datetime) -> WorkflowStore:
    settings = Settings(mongodb_uri="mongodb://unused")
    store = WorkflowStore(settings=settings, database=Database())  # type: ignore[arg-type]
    store.start_fleet(
        FleetIntake(
            workspace_id="workspace-1",
            fleet_id="fleet-1",
            clients=[ClientIntake(client_id="client-1", name="Kriti Agarwal")],
        )
    )
    store.schedule_content_loop("workspace-1", "client-1", due)
    return store


def _patch(monkeypatch, store: WorkflowStore, settings: Settings) -> None:
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "WorkflowStore", lambda _settings: store)


def test_run_once_enqueues_x_and_linkedin_independently(monkeypatch) -> None:
    due = datetime(2026, 7, 12, 6, tzinfo=timezone.utc)
    store = _seeded_store(due)
    settings = Settings(mongodb_uri="mongodb://unused", metrics_webhook_url="")
    _patch(monkeypatch, store, settings)

    result = scheduler.run_once()

    assert result["by_platform"] == {"x": 1, "linkedin": 1}
    assert result["enqueued"] == 2
    platforms = sorted(trigger["trigger_id"].split(":")[2] for trigger in result["triggers"])
    assert platforms == ["linkedin", "x"]
    # No webhook configured -> nothing pushed.
    assert result["pushed"] is False


def test_run_once_is_idempotent_within_a_cadence_window(monkeypatch) -> None:
    due = datetime(2026, 7, 12, 6, tzinfo=timezone.utc)
    store = _seeded_store(due)
    settings = Settings(mongodb_uri="mongodb://unused")
    _patch(monkeypatch, store, settings)

    first = scheduler.run_once()
    second = scheduler.run_once()

    assert first["enqueued"] == 2
    assert second["enqueued"] == 0
    assert second["by_platform"] == {"x": 0, "linkedin": 0}


def test_push_metrics_returns_false_when_no_webhook_configured() -> None:
    store = _seeded_store(datetime(2026, 7, 12, 6, tzinfo=timezone.utc))
    settings = Settings(mongodb_uri="mongodb://unused", metrics_webhook_url="")
    assert scheduler._push_metrics(store, settings) is False


def test_push_metrics_swallows_errors(monkeypatch) -> None:
    store = _seeded_store(datetime(2026, 7, 12, 6, tzinfo=timezone.utc))
    settings = Settings(
        mongodb_uri="mongodb://unused",
        metrics_webhook_url="http://metrics.internal/ingest",
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(scheduler.httpx, "post", _boom)
    # A webhook/import failure must never propagate out of the scheduler.
    assert scheduler._push_metrics(store, settings) is False
