import pytest

from service.auctor.config import Settings
from service.auctor.github_auth import GitHubAuth, GitHubAuthError


class UnusedMemory:
    pass


def auth() -> GitHubAuth:
    settings = Settings(
        mongodb_uri="mongodb://unused",
        github_client_id="client-id",
        github_client_secret="client-secret",
        github_oauth_state_secret="state-secret",
    )
    return GitHubAuth(settings, UnusedMemory())  # type: ignore[arg-type]


def test_oauth_state_round_trip() -> None:
    github = auth()
    state = github.create_state("workspace-1")
    assert github.verify_state(state) == "workspace-1"


def test_oauth_state_rejects_tampering() -> None:
    github = auth()
    state = github.create_state("workspace-1")
    with pytest.raises(GitHubAuthError):
        github.verify_state(state + "changed")


def test_authorization_url_contains_signed_state() -> None:
    url = auth().authorization_url("workspace-1")
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-id" in url
    assert "state=" in url
