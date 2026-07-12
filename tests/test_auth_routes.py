"""Exercises the /api/auth GitHub operator-login router and require_operator gate."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from service.app import session
from service.app.config import settings
from service.app.main import app


@pytest.mark.asyncio
async def test_github_authorize_fails_loud_without_login_credentials(monkeypatch):
    monkeypatch.setattr(settings, "github_login_client_id", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/auth/github/authorize", follow_redirects=False)
    assert resp.status_code == 412
    assert resp.json()["detail"]["kind"] == "missing_login_credentials"


@pytest.mark.asyncio
async def test_github_authorize_fails_clean_without_session_secret_not_500(monkeypatch):
    """Regression test: client_id configured but OPERATOR_SESSION_SECRET unset used to
    raise an unhandled SessionError from session.create_state(), producing a 500. It
    must be a clean 503 instead — this is exactly the prod bug report that motivated
    the fix (GitHub App configured, session secret never set in Coolify)."""
    monkeypatch.setattr(settings, "github_login_client_id", "login_client")
    monkeypatch.setattr(settings, "operator_session_secret", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/auth/github/authorize", follow_redirects=False)
    assert resp.status_code == 503
    assert resp.json()["detail"]["kind"] == "missing_session_secret"


@pytest.mark.asyncio
async def test_github_authorize_redirects_with_credentials(monkeypatch):
    monkeypatch.setattr(settings, "github_login_client_id", "login_client")
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/auth/github/authorize", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=login_client" in location
    assert "scope=read%3Auser" in location


@pytest.mark.asyncio
async def test_me_rejects_missing_session():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "not authenticated"


@pytest.mark.asyncio
async def test_me_returns_operator_for_valid_session(monkeypatch):
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")
    token = session.issue_session(github_login="octocat", github_id=583231)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies={session.SESSION_COOKIE: token}
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"login": "octocat", "gh_id": 583231, "workspace_id": "ws-octocat"}


@pytest.mark.asyncio
async def test_me_rejects_tampered_session(monkeypatch):
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={session.SESSION_COOKIE: "not.a.valid.token"},
    ) as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid session"


class _FakeGithubClient:
    """Stand-in for the ``httpx.AsyncClient`` the callback opens for GitHub calls.

    Patched over ``service.app.routers.auth.httpx.AsyncClient`` only, so the ASGI
    test client (which is a real ``httpx.AsyncClient``) keeps working.
    """

    def __init__(self, *args, **kwargs):
        self.post = AsyncMock(return_value=_json_response({"access_token": "gho_x"}))
        self.get = AsyncMock(return_value=_json_response({"login": "octocat", "id": 42}))

    async def __aenter__(self) -> _FakeGithubClient:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


def _json_response(payload: dict):
    response = AsyncMock()
    response.json = lambda: payload
    return response


@pytest.mark.asyncio
async def test_github_callback_happy_path_sets_operator_cookie(monkeypatch):
    monkeypatch.setattr(settings, "github_login_client_id", "login_client")
    monkeypatch.setattr(settings, "github_login_client_secret", "login_secret")
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")
    state = session.create_state("/")

    transport = ASGITransport(app=app)
    with patch("service.app.routers.auth.httpx.AsyncClient", _FakeGithubClient):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with app.router.lifespan_context(app):
                app.state.db = _FakeDB()
                resp = await client.get(
                    "/api/auth/github/callback",
                    params={"state": state, "code": "auth-code"},
                    follow_redirects=False,
                )

    assert resp.status_code == 302
    assert session.SESSION_COOKIE in resp.cookies
    claims = session.verify_session(resp.cookies[session.SESSION_COOKIE])
    assert claims["login"] == "octocat"
    assert claims["gh_id"] == 42
    assert claims["workspace_id"] == "ws-octocat"


@pytest.mark.asyncio
async def test_github_callback_fails_clean_without_session_secret_not_500(monkeypatch):
    monkeypatch.setattr(settings, "operator_session_secret", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get(
                "/api/auth/github/callback",
                params={"state": "anything", "code": "auth-code"},
                follow_redirects=False,
            )
    assert resp.status_code == 503
    assert resp.json()["detail"]["kind"] == "missing_session_secret"


@pytest.mark.asyncio
async def test_github_callback_rejects_bad_state(monkeypatch):
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get(
                "/api/auth/github/callback",
                params={"state": "not.a.valid.state", "code": "auth-code"},
                follow_redirects=False,
            )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid oauth state"


class _FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs[:length] if length is not None else list(self._docs)


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def find(self, *_args, **_kwargs) -> _FakeCursor:
        return _FakeCursor(self._docs)

    async def count_documents(self, *_args, **_kwargs) -> int:
        return len(self._docs)

    async def update_many(self, *_args, **_kwargs) -> None:
        return None


class _FakeDB:
    """Minimal async Mongo stand-in. fleet_runs is explicit/inspectable; every other
    collection (as touched by auth.py's _backfill_personal_workspace, which iterates
    _WORKSPACE_SCOPED_COLLECTIONS on every login) lazily resolves to an empty fake
    collection, so the backfill's count_documents({"workspace_id": "personal"}) is 0
    and it safely no-ops in tests that aren't specifically exercising it."""

    def __init__(self, fleet_docs: list[dict] | None = None):
        self.fleet_runs = _FakeCollection(fleet_docs or [])
        self._other: dict[str, _FakeCollection] = {}

    def __getattr__(self, name: str) -> _FakeCollection:
        return self._other.setdefault(name, _FakeCollection([]))

    def __getitem__(self, name: str) -> _FakeCollection:
        return getattr(self, name)


@pytest.mark.asyncio
async def test_gated_fleets_route_rejects_without_cookie():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/fleets")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_gated_fleets_route_allows_valid_cookie(monkeypatch):
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")
    token = session.issue_session(github_login="octocat", github_id=42)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies={session.SESSION_COOKIE: token}
    ) as client:
        async with app.router.lifespan_context(app):
            # The gate passes before Mongo is read; swap in a fake db so the read is hermetic.
            monkeypatch.setattr(app.state, "db", _FakeDB([{"fleet_id": "fleet_1"}]))
            resp = await client.get("/api/fleets")
    assert resp.status_code == 200
    assert resp.json() == {"fleets": [{"fleet_id": "fleet_1"}]}


@pytest.mark.asyncio
async def test_credential_login_fails_loud_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "operator_login_username", "")
    monkeypatch.setattr(settings, "operator_login_password", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/api/auth/login", json={"username": "ops", "password": "hunter2"}
            )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_credential_login_fails_clean_without_session_secret_not_500(monkeypatch):
    monkeypatch.setattr(settings, "operator_login_username", "ops")
    monkeypatch.setattr(settings, "operator_login_password", "correct-horse")
    monkeypatch.setattr(settings, "operator_session_secret", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/api/auth/login", json={"username": "ops", "password": "correct-horse"}
            )
    assert resp.status_code == 503
    assert resp.json()["detail"]["kind"] == "missing_session_secret"


@pytest.mark.asyncio
async def test_credential_login_rejects_wrong_password(monkeypatch):
    monkeypatch.setattr(settings, "operator_login_username", "ops")
    monkeypatch.setattr(settings, "operator_login_password", "correct-horse")
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/api/auth/login", json={"username": "ops", "password": "wrong"}
            )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password."


@pytest.mark.asyncio
async def test_credential_login_rejects_wrong_username(monkeypatch):
    monkeypatch.setattr(settings, "operator_login_username", "ops")
    monkeypatch.setattr(settings, "operator_login_password", "correct-horse")
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/api/auth/login", json={"username": "someone-else", "password": "correct-horse"}
            )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_credential_login_sets_operator_cookie_on_success(monkeypatch):
    monkeypatch.setattr(settings, "operator_login_username", "ops")
    monkeypatch.setattr(settings, "operator_login_password", "correct-horse")
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            app.state.db = _FakeDB()
            resp = await client.post(
                "/api/auth/login", json={"username": "ops", "password": "correct-horse"}
            )
    assert resp.status_code == 200
    assert resp.json() == {"login": "ops", "gh_id": 0, "workspace_id": "ws-ops"}
    assert session.SESSION_COOKIE in resp.cookies
    claims = session.verify_session(resp.cookies[session.SESSION_COOKIE])
    assert claims == {"login": "ops", "gh_id": 0, "workspace_id": "ws-ops", "exp": claims["exp"]}


@pytest.mark.asyncio
async def test_credential_login_session_passes_require_operator_gate(monkeypatch):
    """The credential-login cookie must work identically to a GitHub-login cookie
    against every existing require_operator-gated route — same session mechanism."""
    monkeypatch.setattr(settings, "operator_login_username", "ops")
    monkeypatch.setattr(settings, "operator_login_password", "correct-horse")
    monkeypatch.setattr(settings, "operator_session_secret", "test-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            app.state.db = _FakeDB()
            login_resp = await client.post(
                "/api/auth/login", json={"username": "ops", "password": "correct-horse"}
            )
    token = login_resp.cookies[session.SESSION_COOKIE]

    async with AsyncClient(
        transport=transport, base_url="http://test", cookies={session.SESSION_COOKIE: token}
    ) as client:
        async with app.router.lifespan_context(app):
            me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json() == {"login": "ops", "gh_id": 0, "workspace_id": "ws-ops"}


@pytest.mark.asyncio
async def test_logout_clears_cookie():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "auctor_operator=" in resp.headers["set-cookie"]


# --------------------------------------------------------------------------- backfill


class _QueryAwareCollection:
    """Tracks update_many calls and answers count_documents against a real query
    filter (workspace_id equality only — all _backfill_personal_workspace needs)."""

    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.update_many_calls: list[tuple[dict, dict]] = []

    async def count_documents(self, query: dict) -> int:
        ws = query.get("workspace_id")
        return sum(1 for d in self.docs if d.get("workspace_id") == ws)

    async def update_many(self, query: dict, update: dict) -> None:
        self.update_many_calls.append((query, update))
        ws = query.get("workspace_id")
        new_ws = update.get("$set", {}).get("workspace_id")
        for d in self.docs:
            if d.get("workspace_id") == ws:
                d["workspace_id"] = new_ws


class _QueryAwareDB:
    def __init__(self):
        self._collections: dict[str, _QueryAwareCollection] = {}

    def seed(self, name: str, docs: list[dict]) -> None:
        self._collections[name] = _QueryAwareCollection(docs)

    def __getattr__(self, name: str) -> _QueryAwareCollection:
        return self._collections.setdefault(name, _QueryAwareCollection([]))

    def __getitem__(self, name: str) -> _QueryAwareCollection:
        return getattr(self, name)


@pytest.mark.asyncio
async def test_backfill_migrates_legacy_personal_data_to_the_real_workspace():
    from service.app.routers.auth import _backfill_personal_workspace

    db = _QueryAwareDB()
    db.seed("client_pipelines", [{"client_id": "c1", "workspace_id": "personal"}])
    db.seed("content_posts", [{"post_id": "p1", "workspace_id": "personal"}])

    await _backfill_personal_workspace(db, "ws-ops")

    assert db.client_pipelines.docs[0]["workspace_id"] == "ws-ops"
    assert db.content_posts.docs[0]["workspace_id"] == "ws-ops"


@pytest.mark.asyncio
async def test_backfill_is_a_noop_when_target_workspace_already_has_data():
    from service.app.routers.auth import _backfill_personal_workspace

    db = _QueryAwareDB()
    db.seed(
        "client_pipelines",
        [
            {"client_id": "c1", "workspace_id": "personal"},
            {"client_id": "c2", "workspace_id": "ws-ops"},
        ],
    )

    await _backfill_personal_workspace(db, "ws-ops")

    # c1 must NOT have been swept into ws-ops — that workspace already had real data.
    assert db.client_pipelines.docs[0]["workspace_id"] == "personal"
    assert not db.client_pipelines.update_many_calls


@pytest.mark.asyncio
async def test_backfill_is_a_noop_when_no_legacy_data_exists():
    from service.app.routers.auth import _backfill_personal_workspace

    db = _QueryAwareDB()
    db.seed("client_pipelines", [])

    await _backfill_personal_workspace(db, "ws-ops")

    assert not db.client_pipelines.update_many_calls


@pytest.mark.asyncio
async def test_backfill_is_a_noop_for_the_personal_workspace_itself():
    from service.app.routers.auth import _backfill_personal_workspace

    db = _QueryAwareDB()
    db.seed("client_pipelines", [{"client_id": "c1", "workspace_id": "personal"}])

    await _backfill_personal_workspace(db, "personal")

    assert not db.client_pipelines.update_many_calls
