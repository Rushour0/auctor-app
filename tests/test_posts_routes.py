"""Exercises the /api/posts read router against a fake async content_posts collection.

No real Mongo is available in CI, so we stand in a tiny in-memory async double that
mirrors the motor surface the router uses (count_documents / find -> cursor / find_one)
and swap it onto app.state.db after the lifespan opens its real client.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from service.app.main import app


class _FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, key: str, direction: int) -> "_FakeCursor":
        self._docs = sorted(self._docs, key=lambda d: d.get(key), reverse=direction < 0)
        return self

    def skip(self, offset: int) -> "_FakeCursor":
        self._docs = self._docs[offset:]
        return self

    def limit(self, count: int) -> "_FakeCursor":
        self._docs = self._docs[:count]
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        return list(self._docs[:length] if length is not None else self._docs)


def _matches(doc: dict, query: dict) -> bool:
    for key, expected in query.items():
        if "." in key:
            head, tail = key.split(".", 1)
            sub = doc.get(head)
            if not isinstance(sub, dict):
                return False
            if isinstance(expected, dict) and "$exists" in expected:
                if (tail in sub) != expected["$exists"]:
                    return False
            elif sub.get(tail) != expected:
                return False
        elif isinstance(expected, dict) and "$exists" in expected:
            if (key in doc) != expected["$exists"]:
                return False
        elif doc.get(key) != expected:
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
    def __init__(self, docs: list[dict]):
        self.content_posts = _FakeCollection(docs)


def _sample_posts() -> list[dict]:
    return [
        {
            "post_id": "post_1",
            "client_id": "client_a",
            "workspace_id": "ws_1",
            "status": "published",
            "post_type": "thread",
            "updated_at": "2026-07-10T00:00:00Z",
            "platform_status": {"x": "published"},
            "provider_responses": {"x": {"id": "tw_1"}},
        },
        {
            "post_id": "post_2",
            "client_id": "client_a",
            "workspace_id": "ws_1",
            "status": "draft",
            "post_type": "single",
            "updated_at": "2026-07-11T00:00:00Z",
            "platform_status": {"linkedin": "queued"},
        },
        {
            "post_id": "post_3",
            "client_id": "client_b",
            "workspace_id": "ws_2",
            "status": "published",
            "post_type": "single",
            "updated_at": "2026-07-12T00:00:00Z",
            "platform_status": {"x": "published", "linkedin": "published"},
        },
    ]


@pytest.fixture
def fake_client(monkeypatch):
    async def _run(params=None, path="/api/posts"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with app.router.lifespan_context(app):
                app.state.db = _FakeDB(_sample_posts())
                return await client.get(path, params=params)

    return _run


async def test_health_and_version_still_work():
    """Smoke-assert wiring the posts router into main.py did not break existing routes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            health = await client.get("/health")
            version = await client.get("/version")
    assert health.status_code == 200
    assert version.status_code == 200


async def test_list_posts_returns_all_newest_first(fake_client):
    resp = await fake_client()
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    ids = [p["post_id"] for p in body["posts"]]
    assert ids == ["post_3", "post_2", "post_1"]
    assert all("_id" not in p for p in body["posts"])


async def test_list_posts_filters_by_client_and_status(fake_client):
    resp = await fake_client(params={"client_id": "client_a", "status": "published"})
    body = resp.json()
    assert body["total"] == 1
    assert body["posts"][0]["post_id"] == "post_1"


async def test_list_posts_filters_by_post_type(fake_client):
    resp = await fake_client(params={"post_type": "single"})
    body = resp.json()
    assert body["total"] == 2
    assert {p["post_id"] for p in body["posts"]} == {"post_2", "post_3"}
    assert all(p["post_type"] == "single" for p in body["posts"])


async def test_list_posts_platform_filter_uses_per_platform_subdoc(fake_client):
    resp = await fake_client(params={"platform": "linkedin"})
    body = resp.json()
    ids = {p["post_id"] for p in body["posts"]}
    assert ids == {"post_2", "post_3"}
    assert body["total"] == 2


async def test_list_posts_platform_x_filter_is_per_platform_not_boolean(fake_client):
    """?platform=x returns only docs whose platform_status carries an x key, not a boolean flag."""
    resp = await fake_client(params={"platform": "x"})
    body = resp.json()
    # post_1 (x-only) and post_3 (x+linkedin) have an x sub-doc; post_2 is linkedin-only.
    assert {p["post_id"] for p in body["posts"]} == {"post_1", "post_3"}
    assert body["total"] == 2
    assert all("x" in p["platform_status"] for p in body["posts"])


async def test_list_posts_pagination(fake_client):
    resp = await fake_client(params={"limit": 1, "offset": 1})
    body = resp.json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert [p["post_id"] for p in body["posts"]] == ["post_2"]


async def test_get_post_returns_doc_with_platform_subdocs(fake_client):
    resp = await fake_client(path="/api/posts/post_1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["post_id"] == "post_1"
    assert body["platform_status"] == {"x": "published"}
    assert body["provider_responses"] == {"x": {"id": "tw_1"}}
    assert "_id" not in body


async def test_get_post_404_when_missing(fake_client):
    resp = await fake_client(path="/api/posts/post_nope")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "post post_nope not found"
