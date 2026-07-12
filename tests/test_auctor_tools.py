"""Tests for .agent/tools/auctor_tools.py dispatcher and the publish_x / x_engagement_metrics
tool handlers. All X API HTTP calls are mocked; no network traffic occurs.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from service.app import x_integration
from service.app.models import XOAuthCredential
from service.app.tools import publish_x, x_engagement_metrics

REPO_ROOT = Path(__file__).resolve().parents[1]

# Import the CLI dispatcher module directly from its path (it lives outside any package, under
# .agent/tools/, mirroring how it's actually invoked as a script).
_spec = importlib.util.spec_from_file_location(
    "auctor_tools", REPO_ROOT / ".agent" / "tools" / "auctor_tools.py"
)
auctor_tools = importlib.util.module_from_spec(_spec)
sys.modules["auctor_tools"] = auctor_tools
_spec.loader.exec_module(auctor_tools)  # type: ignore[union-attr]


@pytest.fixture(autouse=True)
def x_app_credentials(monkeypatch):
    """Default app-level X credentials for every test in this module; tests that specifically
    exercise the missing_api_key path override these back to blank on their own settings."""
    monkeypatch.setattr(x_integration.settings, "twitter_api_key", "test_key")
    monkeypatch.setattr(x_integration.settings, "twitter_api_secret", "test_secret")


class FakeCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = docs or []

    async def insert_one(self, doc: dict) -> None:
        self.docs.append(doc)

    async def find_one(self, query: dict) -> dict | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def find_one_and_update(self, query: dict, update: dict) -> dict | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return doc
        return None

    async def delete_one(self, query: dict) -> None:
        self.docs = [d for d in self.docs if not all(d.get(k) == v for k, v in query.items())]

    async def find_one_and_delete(self, query: dict) -> dict | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                self.docs.remove(doc)
                return doc
        return None

    async def replace_one(self, query: dict, doc: dict, upsert: bool = False) -> None:
        self.docs = [d for d in self.docs if not all(d.get(k) == v for k, v in query.items())]
        self.docs.append(doc)


class FakeDB:
    def __init__(self) -> None:
        self.x_oauth_states = FakeCollection()
        self.x_oauth_credentials = FakeCollection()
        self.approval_requests = FakeCollection()


def _valid_credential(client_id: str) -> dict:
    return XOAuthCredential(
        client_id=client_id,
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).model_dump()


def _approved_approval(
    client_id: str, approval_id: str, artifact_id: str = "draft_1", consumed: bool = False
) -> dict:
    return {
        "approval_id": approval_id,
        "client_id": client_id,
        "artifact_id": artifact_id,
        "status": "approved",
        "consumed_at": datetime.now(timezone.utc) if consumed else None,
    }


# --- dispatcher routing -----------------------------------------------------------------------


async def test_dispatch_unknown_tool_returns_failed():
    result = await auctor_tools._dispatch("nonexistent_tool", {})
    assert result["status"] == "failed"
    assert "Unknown tool_name" in result["error_message"]


def test_registry_contains_expected_tools():
    assert "publish_x" in auctor_tools.HANDLERS
    assert "x_engagement_metrics" in auctor_tools.HANDLERS


def test_main_missing_argv_returns_usage_error(capsys):
    rc = auctor_tools.main(["auctor_tools.py"])
    assert rc == 2


# --- publish_x ---------------------------------------------------------------------------------


async def test_publish_x_success():
    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))
    db.approval_requests.docs.append(_approved_approval("client_a", "appr_1"))

    fake_response = AsyncMock()
    fake_response.status_code = 201
    fake_response.json = lambda: {"data": {"id": "999", "text": "hi"}}

    with patch("httpx.AsyncClient.post", return_value=fake_response):
        result = await publish_x.run(
            db,
            {
                "client_id": "client_a",
                "draft_id": "draft_1",
                "text": "hello world",
                "approval_id": "appr_1",
            },
        )

    assert result["status"] == "published"
    assert result["post_url"].endswith("999")
    # approval is single-use: now marked consumed
    assert db.approval_requests.docs[0]["consumed_at"] is not None


async def test_publish_x_missing_approval_fails_loud():
    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))
    # no approval_requests doc at all

    result = await publish_x.run(
        db,
        {
            "client_id": "client_a",
            "draft_id": "draft_1",
            "text": "hello world",
            "approval_id": "appr_missing",
        },
    )
    assert result["status"] == "failed"
    assert "missing_approval" in result["error_message"]


async def test_publish_x_approval_never_reused():
    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))
    db.approval_requests.docs.append(_approved_approval("client_a", "appr_1", consumed=True))

    result = await publish_x.run(
        db,
        {
            "client_id": "client_a",
            "draft_id": "draft_1",
            "text": "hello world",
            "approval_id": "appr_1",
        },
    )
    assert result["status"] == "failed"
    assert "missing_approval" in result["error_message"]


async def test_publish_x_missing_api_key_fails_loud(monkeypatch):
    monkeypatch.setattr(x_integration.settings, "twitter_api_key", "")
    monkeypatch.setattr(x_integration.settings, "twitter_api_secret", "")

    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))
    db.approval_requests.docs.append(_approved_approval("client_a", "appr_1"))

    result = await publish_x.run(
        db,
        {
            "client_id": "client_a",
            "draft_id": "draft_1",
            "text": "hello world",
            "approval_id": "appr_1",
        },
    )
    assert result["status"] == "failed"
    assert "missing_api_key" in result["error_message"]
    # infra-only failure must not burn the client's single-use approval
    assert db.approval_requests.docs[0]["consumed_at"] is None


async def test_publish_x_approval_scoped_to_wrong_draft_fails_loud():
    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))
    db.approval_requests.docs.append(
        _approved_approval("client_a", "appr_1", artifact_id="draft_OTHER")
    )

    result = await publish_x.run(
        db,
        {
            "client_id": "client_a",
            "draft_id": "draft_1",
            "text": "hello world",
            "approval_id": "appr_1",
        },
    )
    assert result["status"] == "failed"
    assert "draft" in result["error_message"].lower()


async def test_publish_x_media_assets_without_media_id_fails_loud():
    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))
    db.approval_requests.docs.append(_approved_approval("client_a", "appr_1"))

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        result = await publish_x.run(
            db,
            {
                "client_id": "client_a",
                "draft_id": "draft_1",
                "text": "hello world",
                "approval_id": "appr_1",
                "media_assets": [{"type": "image", "asset_url": "https://example.com/x.png"}],
            },
        )

    assert result["status"] == "failed"
    assert "unsupported_media" in result["error_message"]
    mock_post.assert_not_called()
    assert db.approval_requests.docs[0]["consumed_at"] is None


async def test_publish_x_sends_text_verbatim():
    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))
    db.approval_requests.docs.append(_approved_approval("client_a", "appr_1"))

    fake_response = AsyncMock()
    fake_response.status_code = 201
    fake_response.json = lambda: {"data": {"id": "999"}}

    with patch("httpx.AsyncClient.post", return_value=fake_response) as mock_post:
        await publish_x.run(
            db,
            {
                "client_id": "client_a",
                "draft_id": "draft_1",
                "text": "EXACT text, not rewritten!!",
                "approval_id": "appr_1",
            },
        )

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["text"] == "EXACT text, not rewritten!!"


# --- x_engagement_metrics ------------------------------------------------------------------


async def test_x_engagement_metrics_success():
    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))

    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_response.json = lambda: {
        "data": {
            "id": "12345",
            "public_metrics": {
                "impression_count": 500,
                "like_count": 40,
                "retweet_count": 5,
                "reply_count": 3,
                "bookmark_count": 7,
            },
        }
    }

    with patch("httpx.AsyncClient.get", return_value=fake_response):
        result = await x_engagement_metrics.run(
            db, {"client_id": "client_a", "draft_id": "draft_1", "platform_post_id": "12345"}
        )

    assert result["status"] == "success"
    assert result["impressions"] == 500
    assert result["likes"] == 40
    assert result["reposts"] == 5
    assert result["replies"] == 3
    assert result["bookmarks"] == 7


async def test_x_engagement_metrics_invalid_id_fails_loud():
    db = FakeDB()
    db.x_oauth_credentials.docs.append(_valid_credential("client_a"))

    fake_response = AsyncMock()
    fake_response.status_code = 404
    fake_response.json = lambda: {}

    with patch("httpx.AsyncClient.get", return_value=fake_response):
        result = await x_engagement_metrics.run(
            db, {"client_id": "client_a", "draft_id": "draft_1", "platform_post_id": "bogus"}
        )

    assert result["status"] == "failed"
    assert "invalid_platform_post_id" in result["error_message"]


async def test_x_engagement_metrics_missing_api_key_fails_loud(monkeypatch):
    monkeypatch.setattr(x_integration.settings, "twitter_api_key", "")
    monkeypatch.setattr(x_integration.settings, "twitter_api_secret", "")

    db = FakeDB()
    # no credential on file either, but missing app credential should be hit first via
    # get_valid_access_token -> _require_app_credentials indirectly through refresh path is not
    # reached since there's no stored credential at all: this still fails loud as missing_api_key.
    result = await x_engagement_metrics.run(
        db, {"client_id": "client_a", "draft_id": "draft_1", "platform_post_id": "12345"}
    )
    assert result["status"] == "failed"
    assert "missing_api_key" in result["error_message"]
