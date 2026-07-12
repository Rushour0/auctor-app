"""Signed-cookie session helper for GitHub operator login.

Pure stdlib HMAC-signed tokens (no itsdangerous, no DB, no FastAPI). Two token
kinds share one signing scheme: an operator *session* cookie proving who logged
in, and a short-lived OAuth *state* value protecting the login redirect against
CSRF. Mirrors the sign/verify pattern in service/auctor/github_auth.py so the two
modules stay consistent; the secret is read lazily and fails loud at call time,
never at import/app-boot time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

SESSION_COOKIE = "auctor_operator"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
STATE_TTL_SECONDS = 600


class SessionError(RuntimeError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    from .config import settings

    if not settings.operator_session_secret:
        raise SessionError("OPERATOR_SESSION_SECRET is required")
    return settings.operator_session_secret.encode()


def issue_session(*, github_login: str, github_id: int) -> str:
    """Return a signed session token for a logged-in operator."""
    payload = _b64encode(
        json.dumps(
            {
                "login": github_login,
                "gh_id": github_id,
                "exp": int(time.time()) + SESSION_TTL_SECONDS,
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = _b64encode(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_session(token: str) -> dict:
    """Verify a session token and return its decoded claims."""
    try:
        payload, supplied_signature = token.split(".", 1)
        expected = _b64encode(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied_signature, expected):
            raise SessionError("bad signature")
        data = json.loads(_b64decode(payload))
        if int(data["exp"]) < int(time.time()):
            raise SessionError("expired")
        return data
    except SessionError:
        raise
    except Exception as error:
        raise SessionError("bad signature") from error


def create_state(redirect_after: str = "/") -> str:
    """Return a signed, short-lived OAuth state carrying the post-login redirect."""
    payload = _b64encode(
        json.dumps(
            {
                "redirect_after": redirect_after,
                "expires_at": int(time.time()) + STATE_TTL_SECONDS,
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = _b64encode(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_state(state: str) -> str:
    """Verify an OAuth state and return its ``redirect_after`` target."""
    try:
        payload, supplied_signature = state.split(".", 1)
        expected = _b64encode(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied_signature, expected):
            raise SessionError("bad signature")
        data = json.loads(_b64decode(payload))
        if int(data["expires_at"]) < int(time.time()):
            raise SessionError("expired")
        return str(data["redirect_after"])
    except SessionError:
        raise
    except Exception as error:
        raise SessionError("bad signature") from error
