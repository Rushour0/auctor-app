from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from service.auctor.config import Settings
from service.auctor.memory import AuctorMemory


def nested_get(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


class Cursor(list):
    def sort(self, key: str, direction: int) -> "Cursor":
        return Cursor(sorted(self, key=lambda row: nested_get(row, key), reverse=direction < 0))

    def limit(self, size: int) -> "Cursor":
        return Cursor(self[:size])


class Collection:
    def __init__(self, documents: list[dict[str, Any]]):
        self.documents = documents

    def find(self, query: dict[str, Any], _: dict[str, int]) -> Cursor:
        timestamp_field = next(key for key in query if key != "workspace_id")
        bounds = query[timestamp_field]
        return Cursor(
            deepcopy(row)
            for row in self.documents
            if row["workspace_id"] == query["workspace_id"]
            and bounds["$gte"] <= nested_get(row, timestamp_field) < bounds["$lt"]
        )


class Database:
    def __init__(self, documents: list[dict[str, Any]]):
        self.events = Collection(documents)
        self.metric_observations = Collection(documents)
        self.trend_items = Collection(documents)
        self.raw_records = Collection(documents)


def test_recent_data_uses_collection_time_and_bounded_window() -> None:
    until = datetime(2026, 7, 12, 12, tzinfo=timezone.utc)
    recent = until - timedelta(hours=1)
    old = until - timedelta(hours=7)
    documents = [
        {
            "workspace_id": "workspace-1",
            "external_id": "recent",
            "collected_at": recent,
            "provenance": {"collected_at": recent},
        },
        {
            "workspace_id": "workspace-1",
            "external_id": "old",
            "collected_at": old,
            "provenance": {"collected_at": old},
        },
        {
            "workspace_id": "other",
            "external_id": "other-workspace",
            "collected_at": recent,
            "provenance": {"collected_at": recent},
        },
    ]
    memory = AuctorMemory(
        settings=Settings(mongodb_uri="mongodb://unused"),
        database=Database(documents),  # type: ignore[arg-type]
    )

    result = memory.recent_data("workspace-1", until - timedelta(hours=6), until)

    assert result["counts"] == {"events": 1, "metrics": 1, "trends": 1, "raw_records": 1}
    assert result["events"][0]["external_id"] == "recent"
    assert result["window"] == {"since": until - timedelta(hours=6), "until": until}


def test_recent_data_rejects_unbounded_or_invalid_inputs() -> None:
    memory = AuctorMemory(
        settings=Settings(mongodb_uri="mongodb://unused"),
        database=Database([]),  # type: ignore[arg-type]
    )
    now = datetime.now(timezone.utc)

    for since, until, limit in ((now, now, 10), (now - timedelta(hours=1), now, 0)):
        try:
            memory.recent_data("workspace-1", since, until, limit)
        except ValueError:
            pass
        else:
            raise AssertionError("Expected invalid recent-data window to be rejected")
