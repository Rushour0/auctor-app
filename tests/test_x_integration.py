"""Unit tests for service/app/x_integration.py: OAuth token storage/refresh mechanics.

All X API HTTP calls are mocked via unittest.mock.AsyncMock patches on httpx.AsyncClient so no
network traffic occurs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from service.app import x_integration
from service.app.models import XOAuthCredential


class FakeCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = docs or []
        self.inserted: list[dict] = []
        self.replaced: list[dict] = []

    async def insert_one(self, doc: dict) -> None:
        self.inserted.append(doc)
        self.docs.append(doc)

    async def find_one(self, query: dict) -> dict | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def delete_one(self, query: dict) -> None:
        self.docs = [d for d in self.docs if not all(d.get(k) == v for k, v in query.items())]

    async def replace_one(self, query: dict, doc: dict, upsert: bool = False) -> None:
        self.replaced.append(doc)
        self.docs = [d for d in self.docs if not all(d.get(k) == v for k, v in query.items())]
        self.docs.append(doc)


class FakeDB:
    def __init__(self) -> None:
        self.x_oauth_states = FakeCollection()
        self.x_oauth_credentials = FakeCollection()
        self.approval_requests = FakeCollection()


@pytest.fixture
def db() -> FakeDB:
    return FakeDB()


@pytest.fixture(autouse=True)
def x_creds(monkeypatch):
    monkeypatch.setattr(x_integration.settings, "twitter_api_key", "test_key")
    monkeypatch.setattr(x_integration.settings, "twitter_api_secret", "test_secret")


async def test_start_authorize_fails_loud_without_app_credentials(db, monkeypatch):
    monkeypatch.setattr(x_integration.settings, "twitter_api_key", "")
    monkeypatch.setattr(x_integration.settings, "twitter_api_secret", "")
    with pytest.raises(x_integration.XApiError) as exc:
        await x_integration.start_authorize(db, "client_a")
    assert exc.value.kind == "missing_api_key"


async def test_start_authorize_persists_pkce_state_and_builds_url(db):
    url = await x_integration.start_authorize(db, "client_a")
    assert url.startswith(x_integration.AUTHORIZE_URL)
    assert "code_challenge=" in url
    assert "client_id=test_key" in url
    assert len(db.x_oauth_states.docs) == 1
    assert db.x_oauth_states.docs[0]["client_id"] == "client_a"


async def test_handle_callback_exchanges_code_and_stores_credential(db):
    await x_integration.start_authorize(db, "client_a")
    state = db.x_oauth_states.docs[0]["state"]

    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_response.json = lambda: {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 7200,
    }

    with patch("httpx.AsyncClient.post", return_value=fake_response):
        credential = await x_integration.handle_callback(db, state=state, code="auth-code")

    assert credential.client_id == "client_a"
    assert credential.access_token == "access-1"
    assert credential.refresh_token == "refresh-1"
    # state is single-use: consumed after the callback
    assert db.x_oauth_states.docs == []
    assert db.x_oauth_credentials.docs[0]["access_token"] == "access-1"


async def test_handle_callback_rejects_unknown_state(db):
    with pytest.raises(x_integration.XApiError) as exc:
        await x_integration.handle_callback(db, state="bogus", code="c")
    assert exc.value.kind == "invalid_oauth_state"


async def test_get_valid_access_token_returns_unexpired_token(db):
    credential = XOAuthCredential(
        client_id="client_a",
        access_token="fresh-token",
        refresh_token="refresh-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.x_oauth_credentials.docs.append(credential.model_dump())

    token = await x_integration.get_valid_access_token(db, "client_a")
    assert token == "fresh-token"


async def test_get_valid_access_token_refreshes_expired_token_and_rotates_refresh_token(db):
    credential = XOAuthCredential(
        client_id="client_a",
        access_token="stale-token",
        refresh_token="refresh-old",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.x_oauth_credentials.docs.append(credential.model_dump())

    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_response.json = lambda: {
        "access_token": "fresh-token-2",
        "refresh_token": "refresh-new",
        "expires_in": 7200,
    }

    with patch("httpx.AsyncClient.post", return_value=fake_response):
        token = await x_integration.get_valid_access_token(db, "client_a")

    assert token == "fresh-token-2"
    stored = db.x_oauth_credentials.docs[0]
    assert stored["refresh_token"] == "refresh-new"


async def test_get_valid_access_token_missing_credential_fails_loud(db):
    with pytest.raises(x_integration.XApiError) as exc:
        await x_integration.get_valid_access_token(db, "client_unknown")
    assert exc.value.kind == "missing_api_key"


async def test_fleet_isolation_credential_lookup_scoped_by_client_id(db):
    other = XOAuthCredential(
        client_id="client_other",
        access_token="other-token",
        refresh_token="other-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.x_oauth_credentials.docs.append(other.model_dump())

    with pytest.raises(x_integration.XApiError):
        await x_integration.get_valid_access_token(db, "client_a")


async def test_post_tweet_success():
    fake_response = AsyncMock()
    fake_response.status_code = 201
    fake_response.json = lambda: {"data": {"id": "12345", "text": "hello"}}

    with patch("httpx.AsyncClient.post", return_value=fake_response):
        result = await x_integration.post_tweet("token", "hello")
    assert result["data"]["id"] == "12345"


async def test_get_tweet_public_metrics_success():
    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_response.json = lambda: {
        "data": {
            "id": "12345",
            "public_metrics": {
                "impression_count": 100,
                "like_count": 10,
                "retweet_count": 2,
                "reply_count": 1,
                "bookmark_count": 3,
            },
        }
    }

    with patch("httpx.AsyncClient.get", return_value=fake_response):
        metrics = await x_integration.get_tweet_public_metrics("token", "12345")
    assert metrics["like_count"] == 10


async def test_get_tweet_public_metrics_invalid_id_fails_loud():
    fake_response = AsyncMock()
    fake_response.status_code = 404
    fake_response.json = lambda: {}

    with patch("httpx.AsyncClient.get", return_value=fake_response):
        with pytest.raises(x_integration.XApiError) as exc:
            await x_integration.get_tweet_public_metrics("token", "bogus")
    assert exc.value.kind == "invalid_platform_post_id"
