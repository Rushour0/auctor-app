"""Shared in-memory double mimicking the slice of pymongo's sync `Database` surface
WorkflowStore (and anything built on it, e.g. ContentAgencyRunner) actually uses.

Extracted from test_workflow_persistence.py so new test modules (e.g. the cron ->
content-job integration tests) don't re-implement query-matching semantics. Extend
this file, not a private copy, when a WorkflowStore method needs another operator or
collection call CI's headless test run can't get from a real mongod (ci.yml has no
Mongo service, so this fake IS the integration-test substrate for sync-pymongo code).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


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
            if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
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
    def sort(self, key: str, direction: int) -> "Cursor":
        return Cursor(sorted(self, key=lambda row: row.get(key), reverse=direction < 0))

    def limit(self, count: int) -> "Cursor":
        return Cursor(self[: max(0, count)])


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

    def find_one(
        self, query: dict[str, Any], projection: dict[str, int] | None = None
    ) -> dict[str, Any] | None:
        for row in self.documents:
            if not matches(row, query):
                continue
            result = deepcopy(row)
            if projection and projection.get("_id") == 0:
                result.pop("_id", None)
            return result
        return None

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
