"""Exercises the public, no-signup POST /api/demo/suggest route and the underlying
service.app.demo Linkup-research + OpenAI-draft helpers.

No real Mongo/Linkup/OpenAI in CI: the route's rate-limit collection is a tiny
fake async double (same pattern as test_posts_routes.py); the two external calls
in service/app/demo.py are exercised directly against a fake httpx.Client so no
network I/O happens in the test suite.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from service.app import demo
from service.app.config import settings
from service.app.main import app


# --------------------------------------------------------------------------- fakes


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._payload


class _FakeHttpClient:
    """Records calls and replays canned responses in order, one per .post()."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((url, kwargs))
        return self._responses.pop(0)

    def close(self) -> None:
        pass


class _FakeDemoCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def count_documents(self, query: dict) -> int:
        since = query.get("requested_at", {}).get("$gte")
        ip = query.get("ip")
        return sum(1 for d in self.docs if d["ip"] == ip and d["requested_at"] >= since)

    async def insert_one(self, doc: dict) -> None:
        self.docs.append(doc)


class _FakeDB:
    def __init__(self):
        self.demo_requests = _FakeDemoCollection()


# --------------------------------------------------------------------------- unit: research_handle


def test_research_handle_requires_a_handle(monkeypatch):
    monkeypatch.setattr(settings, "linkup_api_key", "key")
    with pytest.raises(demo.DemoError) as exc:
        demo.research_handle(None, None)
    assert exc.value.kind == "missing_handle"


def test_research_handle_fails_loud_without_linkup_key(monkeypatch):
    monkeypatch.setattr(settings, "linkup_api_key", "")
    with pytest.raises(demo.DemoError) as exc:
        demo.research_handle("https://linkedin.com/in/someone", None)
    assert exc.value.kind == "missing_api_key"


def test_research_handle_returns_findings_from_linkup(monkeypatch):
    monkeypatch.setattr(settings, "linkup_api_key", "key")
    fake = _FakeHttpClient(
        [
            _FakeResponse(
                200,
                {
                    "results": [
                        {"name": "Shipped v2 of their product", "url": "https://x.com/a/status/1"},
                        {"title": "", "url": ""},
                    ]
                },
            )
        ]
    )
    findings = demo.research_handle("https://linkedin.com/in/someone", None, client=fake)
    assert findings == [
        {"claim": "Shipped v2 of their product", "source_url": "https://x.com/a/status/1"}
    ]


def test_research_handle_raises_no_signal_when_linkup_returns_nothing(monkeypatch):
    monkeypatch.setattr(settings, "linkup_api_key", "key")
    fake = _FakeHttpClient([_FakeResponse(200, {"results": []})])
    with pytest.raises(demo.DemoError) as exc:
        demo.research_handle(None, "someone", client=fake)
    assert exc.value.kind == "no_signal"


def test_research_handle_raises_search_failed_on_error_response(monkeypatch):
    monkeypatch.setattr(settings, "linkup_api_key", "key")
    fake = _FakeHttpClient([_FakeResponse(500, {})])
    with pytest.raises(demo.DemoError) as exc:
        demo.research_handle(None, "someone", client=fake)
    assert exc.value.kind == "search_failed"


def test_research_handle_caps_findings_to_eight(monkeypatch):
    monkeypatch.setattr(settings, "linkup_api_key", "key")
    results = [{"name": f"finding {i}", "url": f"https://x.com/{i}"} for i in range(20)]
    fake = _FakeHttpClient([_FakeResponse(200, {"results": results})])
    findings = demo.research_handle(None, "someone", client=fake)
    assert len(findings) == 8
    assert findings[0]["source_url"] == "https://x.com/0"


# --------------------------------------------------------------------------- unit: draft_suggestions


def _openai_response(suggestions: list[dict]) -> _FakeResponse:
    import json

    return _FakeResponse(
        200,
        {
            "choices": [
                {"message": {"content": json.dumps({"suggestions": suggestions})}}
            ]
        },
    )


def test_draft_suggestions_fails_loud_without_openai_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(demo.DemoError) as exc:
        demo.draft_suggestions([{"claim": "x", "source_url": "https://x.com/1"}])
    assert exc.value.kind == "missing_api_key"


def test_draft_suggestions_drops_ungrounded_suggestions(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "key")
    findings = [{"claim": "Shipped v2", "source_url": "https://x.com/1"}]

    fake = _FakeHttpClient(
        [
            _openai_response(
                [
                    {
                        "post_type": "ship-announcement",
                        "topic": "v2 launch",
                        "draft": "We shipped v2!",
                        "finding_index": 0,
                    },
                    # Out-of-range index — must be dropped, never fabricated.
                    {
                        "post_type": "hot-take",
                        "topic": "invented",
                        "draft": "made up claim",
                        "finding_index": 5,
                    },
                ]
            )
        ]
    )
    out = demo.draft_suggestions(findings, client=fake)
    assert len(out) == 1
    assert out[0]["source_url"] == "https://x.com/1"


def test_draft_suggestions_raises_no_signal_if_nothing_grounded(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "key")
    fake = _FakeHttpClient([_openai_response([{"finding_index": 9}])])
    with pytest.raises(demo.DemoError) as exc:
        demo.draft_suggestions([{"claim": "x", "source_url": "https://x.com/1"}], client=fake)
    assert exc.value.kind == "no_signal"


def test_draft_suggestions_caps_to_three_even_if_more_are_grounded(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "key")
    findings = [{"claim": f"finding {i}", "source_url": f"https://x.com/{i}"} for i in range(5)]
    suggestions = [
        {"post_type": "milestone", "topic": f"t{i}", "draft": f"d{i}", "finding_index": i}
        for i in range(5)
    ]
    fake = _FakeHttpClient([_openai_response(suggestions)])
    out = demo.draft_suggestions(findings, client=fake)
    assert len(out) == 3


# --------------------------------------------------------------------------- integration: run_public_suggestion


def test_run_public_suggestion_wires_research_into_draft(monkeypatch):
    """Real end-to-end wiring test (not mocking run_public_suggestion itself, unlike
    the route tests below) — proves research_handle's findings actually flow into
    draft_suggestions, not just that each function works in isolation."""
    monkeypatch.setattr(settings, "linkup_api_key", "key")
    monkeypatch.setattr(settings, "openai_api_key", "key")

    linkup_response = _FakeResponse(
        200, {"results": [{"name": "Shipped v2", "url": "https://x.com/1"}]}
    )
    openai_response = _openai_response(
        [
            {
                "post_type": "ship-announcement",
                "topic": "v2",
                "draft": "We shipped v2!",
                "finding_index": 0,
            }
        ]
    )

    calls = {"n": 0}

    def _client_factory(*args, **kwargs):
        calls["n"] += 1
        return _FakeHttpClient([linkup_response if calls["n"] == 1 else openai_response])

    monkeypatch.setattr(demo.httpx, "Client", _client_factory)

    result = demo.run_public_suggestion("https://linkedin.com/in/someone", None)

    assert result["sources"] == ["https://x.com/1"]
    assert result["suggestions"][0]["draft"] == "We shipped v2!"
    assert result["suggestions"][0]["source_url"] == "https://x.com/1"
    assert calls["n"] == 2


# --------------------------------------------------------------------------- route


@pytest.fixture
def demo_client():
    async def _run(json_body: dict, ip: str = "1.2.3.4"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with app.router.lifespan_context(app):
                app.state.db = _FakeDB()
                return await client.post(
                    "/api/demo/suggest", json=json_body, headers={"x-forwarded-for": ip}
                )

    return _run


@pytest.mark.asyncio
async def test_suggest_requires_a_handle(demo_client):
    resp = await demo_client({})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_suggest_success(demo_client, monkeypatch):
    monkeypatch.setattr(
        demo,
        "run_public_suggestion",
        lambda linkedin_url, twitter_handle: {
            "suggestions": [
                {
                    "post_type": "milestone",
                    "topic": "t",
                    "draft": "d",
                    "source_url": "https://x.com/1",
                }
            ],
            "sources": ["https://x.com/1"],
        },
    )
    resp = await demo_client({"twitter_handle": "someone"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggestions"][0]["source_url"] == "https://x.com/1"


@pytest.mark.asyncio
async def test_suggest_maps_demo_error_to_http_status(demo_client, monkeypatch):
    def _raise(linkedin_url, twitter_handle):
        raise demo.DemoError("no_signal", "nothing found")

    monkeypatch.setattr(demo, "run_public_suggestion", _raise)
    resp = await demo_client({"twitter_handle": "someone"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "nothing found"


@pytest.mark.asyncio
async def test_suggest_rate_limited_after_daily_cap(monkeypatch):
    monkeypatch.setattr(settings, "demo_rate_limit_per_day", 2)
    called = {"n": 0}

    def _track(linkedin_url, twitter_handle):
        called["n"] += 1
        return {"suggestions": [], "sources": []}

    monkeypatch.setattr(demo, "run_public_suggestion", _track)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            app.state.db = _FakeDB()
            headers = {"x-forwarded-for": "9.9.9.9"}
            body = {"twitter_handle": "someone"}
            r1 = await client.post("/api/demo/suggest", json=body, headers=headers)
            r2 = await client.post("/api/demo/suggest", json=body, headers=headers)
            r3 = await client.post("/api/demo/suggest", json=body, headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert called["n"] == 2


@pytest.mark.asyncio
async def test_suggest_rate_limit_is_scoped_per_ip(monkeypatch):
    monkeypatch.setattr(settings, "demo_rate_limit_per_day", 1)
    monkeypatch.setattr(
        demo, "run_public_suggestion", lambda *a: {"suggestions": [], "sources": []}
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            app.state.db = _FakeDB()
            body = {"twitter_handle": "someone"}
            r1 = await client.post(
                "/api/demo/suggest", json=body, headers={"x-forwarded-for": "1.1.1.1"}
            )
            r2 = await client.post(
                "/api/demo/suggest", json=body, headers={"x-forwarded-for": "2.2.2.2"}
            )

    assert r1.status_code == 200
    assert r2.status_code == 200
