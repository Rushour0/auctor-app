from __future__ import annotations

import time

import pytest

from service.app import config, session


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(config.settings, "operator_session_secret", "operator-secret")


def test_session_round_trip(secret) -> None:
    token = session.issue_session(github_login="octocat", github_id=583231)
    data = session.verify_session(token)
    assert data["login"] == "octocat"
    assert data["gh_id"] == 583231
    assert data["workspace_id"] == "ws-octocat"
    assert data["exp"] > int(time.time())


def test_workspace_id_for_login_is_stable_and_slugified() -> None:
    assert session.workspace_id_for_login("octocat") == "ws-octocat"
    assert session.workspace_id_for_login("Octocat") == "ws-octocat"  # case-insensitive
    assert session.workspace_id_for_login("octocat") == session.workspace_id_for_login("octocat")


def test_workspace_id_for_login_slugifies_special_characters() -> None:
    assert session.workspace_id_for_login("Rushikesh Patade") == "ws-rushikesh-patade"
    assert session.workspace_id_for_login("user+tag@x") == "ws-user-tag-x"


def test_workspace_id_for_login_falls_back_when_nothing_slugifiable() -> None:
    assert session.workspace_id_for_login("!!!") == "ws-operator"


def test_session_rejects_tampering(secret) -> None:
    token = session.issue_session(github_login="octocat", github_id=1)
    with pytest.raises(session.SessionError):
        session.verify_session(token + "changed")


def test_session_rejects_expired(secret, monkeypatch) -> None:
    token = session.issue_session(github_login="octocat", github_id=1)
    future = time.time() + session.SESSION_TTL_SECONDS + 1
    monkeypatch.setattr(session.time, "time", lambda: future)
    with pytest.raises(session.SessionError, match="expired"):
        session.verify_session(token)


def test_session_rejects_wrong_secret(monkeypatch) -> None:
    monkeypatch.setattr(config.settings, "operator_session_secret", "secret-one")
    token = session.issue_session(github_login="octocat", github_id=1)
    # Rotating the secret must make compare_digest reject the old signature.
    monkeypatch.setattr(config.settings, "operator_session_secret", "secret-two")
    with pytest.raises(session.SessionError):
        session.verify_session(token)


def test_secret_required_fails_loud(monkeypatch) -> None:
    monkeypatch.setattr(config.settings, "operator_session_secret", "")
    with pytest.raises(session.SessionError, match="OPERATOR_SESSION_SECRET is required"):
        session.issue_session(github_login="octocat", github_id=1)


def test_state_round_trip(secret) -> None:
    state = session.create_state("/posts")
    assert session.verify_state(state) == "/posts"


def test_state_default_redirect(secret) -> None:
    assert session.verify_state(session.create_state()) == "/"


def test_state_rejects_tampering(secret) -> None:
    state = session.create_state("/crons")
    with pytest.raises(session.SessionError):
        session.verify_state(state + "x")


def test_state_rejects_expired(secret, monkeypatch) -> None:
    state = session.create_state("/metrics")
    future = time.time() + session.STATE_TTL_SECONDS + 1
    monkeypatch.setattr(session.time, "time", lambda: future)
    with pytest.raises(session.SessionError, match="expired"):
        session.verify_state(state)
