import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from .config import Settings
from .memory import AuctorMemory, utc_now
from .models import ProviderConnection

GITHUB_API = "https://api.github.com"


class GitHubAuthError(RuntimeError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class GitHubAuth:
    def __init__(self, settings: Settings, memory: AuctorMemory):
        self.settings = settings
        self.memory = memory

    def _state_secret(self) -> bytes:
        secret = self.settings.github_oauth_state_secret or self.settings.github_client_secret
        if not secret:
            raise GitHubAuthError("GITHUB_OAUTH_STATE_SECRET is required")
        return secret.encode()

    def create_state(self, workspace_id: str) -> str:
        payload = _b64encode(
            json.dumps(
                {"workspace_id": workspace_id, "expires_at": int(time.time()) + 600},
                separators=(",", ":"),
            ).encode()
        )
        signature = _b64encode(
            hmac.new(self._state_secret(), payload.encode(), hashlib.sha256).digest()
        )
        return f"{payload}.{signature}"

    def verify_state(self, state: str) -> str:
        try:
            payload, supplied_signature = state.split(".", 1)
            expected = _b64encode(
                hmac.new(self._state_secret(), payload.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected):
                raise GitHubAuthError("Invalid GitHub OAuth state")
            data = json.loads(_b64decode(payload))
            if int(data["expires_at"]) < int(time.time()):
                raise GitHubAuthError("Expired GitHub OAuth state")
            return str(data["workspace_id"])
        except GitHubAuthError:
            raise
        except Exception as error:
            raise GitHubAuthError("Invalid GitHub OAuth state") from error

    def authorization_url(self, workspace_id: str) -> str:
        if not self.settings.github_client_id:
            raise GitHubAuthError("GITHUB_CLIENT_ID is required")
        query = urlencode(
            {
                "client_id": self.settings.github_client_id,
                "redirect_uri": self.settings.github_oauth_callback_url,
                "state": self.create_state(workspace_id),
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    def _exchange_code(self, code: str) -> str:
        response = httpx.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": self.settings.github_client_id,
                "client_secret": self.settings.github_client_secret,
                "code": code,
                "redirect_uri": self.settings.github_oauth_callback_url,
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise GitHubAuthError("GitHub did not return an OAuth access token")
        return str(token)

    def complete_oauth(
        self, code: str, state: str, installation_id: int | None = None
    ) -> ProviderConnection:
        workspace_id = self.verify_state(state)
        user_token = self._exchange_code(code)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {user_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.get(f"{GITHUB_API}/user/installations", headers=headers, timeout=30)
        response.raise_for_status()
        installations = response.json().get("installations", [])
        if installation_id is not None:
            installations = [row for row in installations if row.get("id") == installation_id]
        if len(installations) != 1:
            raise GitHubAuthError(
                "Install the Auctor GitHub App, or specify which installation to connect"
            )
        installation = installations[0]
        selected_id = int(installation["id"])
        repositories_response = httpx.get(
            f"{GITHUB_API}/user/installations/{selected_id}/repositories",
            headers=headers,
            timeout=30,
        )
        repositories_response.raise_for_status()
        repositories = [
            {"id": repo.get("id"), "full_name": repo.get("full_name")}
            for repo in repositories_response.json().get("repositories", [])
        ]
        account = installation.get("account") or {}
        now = utc_now()
        connection = ProviderConnection(
            workspace_id=workspace_id,
            installation_id=selected_id,
            account_id=account.get("id"),
            account_login=account.get("login", "unknown"),
            repository_selection=installation.get("repository_selection", "selected"),
            repositories=repositories,
            status="active",
            connected_at=now,
            updated_at=now,
        )
        self.memory.save_provider_connection(connection)
        return connection

    def _private_key(self) -> str:
        if self.settings.github_private_key_base64:
            return base64.b64decode(self.settings.github_private_key_base64).decode()
        if self.settings.github_private_key:
            return self.settings.github_private_key.replace("\\n", "\n")
        raise GitHubAuthError("GITHUB_PRIVATE_KEY or GITHUB_PRIVATE_KEY_BASE64 is required")

    def installation_token(self, workspace_id: str) -> str:
        connection = self.memory.get_provider_connection(workspace_id, "github")
        if not connection or connection.get("status") != "active":
            raise GitHubAuthError("GitHub is not connected for this workspace")
        now = datetime.now(timezone.utc)
        app_jwt = jwt.encode(
            {
                "iat": int((now - timedelta(seconds=60)).timestamp()),
                "exp": int((now + timedelta(minutes=9)).timestamp()),
                "iss": self.settings.github_app_id,
            },
            self._private_key(),
            algorithm="RS256",
        )
        response = httpx.post(
            f"{GITHUB_API}/app/installations/{connection['installation_id']}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {app_jwt}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        response.raise_for_status()
        return str(response.json()["token"])

    def verify_webhook(self, body: bytes, signature: str | None) -> None:
        if not self.settings.github_webhook_secret or not signature:
            raise GitHubAuthError("Missing GitHub webhook signature")
        expected = (
            "sha256="
            + hmac.new(
                self.settings.github_webhook_secret.encode(), body, hashlib.sha256
            ).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            raise GitHubAuthError("Invalid GitHub webhook signature")

    def apply_webhook(self, event: str, payload: dict[str, Any]) -> None:
        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        if not installation_id:
            return
        connection = self.memory.db.provider_connections.find_one(
            {"provider": "github", "installation_id": installation_id}
        )
        if not connection:
            return
        status = connection.get("status", "active")
        if event == "installation" and payload.get("action") == "deleted":
            status = "revoked"
        elif event == "installation" and payload.get("action") == "suspend":
            status = "suspended"
        elif event == "installation" and payload.get("action") == "unsuspend":
            status = "active"
        updates: dict[str, Any] = {"status": status, "updated_at": utc_now()}
        if event == "installation_repositories":
            current = {repo["id"]: repo for repo in connection.get("repositories", [])}
            for repo in payload.get("repositories_added", []):
                current[repo["id"]] = {"id": repo["id"], "full_name": repo["full_name"]}
            for repo in payload.get("repositories_removed", []):
                current.pop(repo["id"], None)
            updates["repositories"] = list(current.values())
        self.memory.db.provider_connections.update_one(
            {"_id": connection["_id"]}, {"$set": updates}
        )
