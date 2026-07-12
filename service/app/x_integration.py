"""Twitter/X API v2 integration: per-client OAuth 2.0 Authorization Code + PKCE, and the two
X API v2 calls Auctor needs (publish a tweet, read a tweet's public metrics).

Every function that touches Mongo takes an explicit ``client_id`` and scopes its query by it —
fleet isolation: one client's X token must never leak into another client's request (see
``.agent/prompts/domains/auctor/policy.md`` FLEET ISOLATION).

Nothing here reads ``settings.twitter_api_key``/``twitter_api_secret`` at import time. Settings
must load fine with those blank; the fail-loud check happens inside ``require_app_credentials``,
called only when a real API call is about to be made.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import settings
from .models import XOAuthCredential, XOAuthState

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
TWEETS_URL = "https://api.twitter.com/2/tweets"
OAUTH_SCOPES = "tweet.read tweet.write users.read offline.access"

# Access tokens are refreshed a little ahead of their real expiry to avoid racing X's clock.
REFRESH_SKEW = timedelta(seconds=60)


class XApiError(Exception):
    """Raised for any X-integration failure. ``kind`` maps to a manifest's fail_loud_on code."""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        self.message = message
        super().__init__(message)


def require_app_credentials() -> tuple[str, str]:
    """Fail loud, at call time, if the app-level X developer credentials are unset."""
    if not settings.twitter_api_key or not settings.twitter_api_secret:
        raise XApiError(
            "missing_api_key",
            "TWITTER_API_KEY/TWITTER_API_SECRET are not configured — cannot call the X API.",
        )
    return settings.twitter_api_key, settings.twitter_api_secret


def _basic_auth_header(api_key: str, api_secret: str) -> str:
    raw = f"{api_key}:{api_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for the S256 PKCE method."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


async def start_authorize(db: AsyncIOMotorDatabase, client_id: str) -> str:
    """Persist PKCE state for ``client_id`` and return the X authorize redirect URL."""
    api_key, _ = require_app_credentials()
    code_verifier, code_challenge = _generate_pkce_pair()
    state_doc = XOAuthState(client_id=client_id, code_verifier=code_verifier)
    await db.x_oauth_states.insert_one(state_doc.model_dump())

    params = {
        "response_type": "code",
        "client_id": api_key,
        "redirect_uri": settings.twitter_redirect_uri,
        "scope": OAUTH_SCOPES,
        "state": state_doc.state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def handle_callback(db: AsyncIOMotorDatabase, *, state: str, code: str) -> XOAuthCredential:
    """Consume the one-time PKCE state, exchange ``code`` for tokens, and persist them."""
    api_key, api_secret = require_app_credentials()

    state_doc = await db.x_oauth_states.find_one_and_delete({"state": state})
    if state_doc is None:
        raise XApiError("invalid_oauth_state", "Unknown or already-consumed OAuth state.")
    client_id = state_doc["client_id"]
    code_verifier = state_doc["code_verifier"]

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.twitter_redirect_uri,
        "code_verifier": code_verifier,
        "client_id": api_key,
    }
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(
            TOKEN_URL,
            data=body,
            headers={
                "Authorization": _basic_auth_header(api_key, api_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if resp.status_code != 200:
        raise XApiError("oauth_exchange_failed", f"X token exchange failed: {resp.text}")

    payload = resp.json()
    credential = _credential_from_token_response(client_id, payload)
    await db.x_oauth_credentials.replace_one(
        {"client_id": client_id}, credential.model_dump(), upsert=True
    )
    return credential


def _credential_from_token_response(client_id: str, payload: dict[str, Any]) -> XOAuthCredential:
    expires_in = int(payload.get("expires_in", 7200))
    return XOAuthCredential(
        client_id=client_id,
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        scope=payload.get("scope", OAUTH_SCOPES),
    )


async def _refresh(db: AsyncIOMotorDatabase, credential: XOAuthCredential) -> XOAuthCredential:
    """Exchange a refresh_token for a new access_token, honoring X's refresh-token rotation."""
    api_key, api_secret = require_app_credentials()
    body = {
        "grant_type": "refresh_token",
        "refresh_token": credential.refresh_token,
        "client_id": api_key,
    }
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(
            TOKEN_URL,
            data=body,
            headers={
                "Authorization": _basic_auth_header(api_key, api_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if resp.status_code != 200:
        raise XApiError("oauth_refresh_failed", f"X token refresh failed: {resp.text}")

    payload = resp.json()
    # X rotates the refresh_token on every use — the response's refresh_token replaces ours.
    payload.setdefault("refresh_token", credential.refresh_token)
    new_credential = _credential_from_token_response(credential.client_id, payload)
    await db.x_oauth_credentials.replace_one(
        {"client_id": credential.client_id}, new_credential.model_dump(), upsert=True
    )
    return new_credential


async def get_valid_access_token(db: AsyncIOMotorDatabase, client_id: str) -> str:
    """Return a live access_token for ``client_id``, refreshing first if it's expired/near-expiry.

    Scoped strictly by ``client_id`` — never reads or returns another client's credential. Fails
    loud on a missing app-level API key even when a stored, unexpired token exists: a call that
    later needs to refresh must not silently succeed today and fail unpredictably tomorrow.
    """
    require_app_credentials()
    doc = await db.x_oauth_credentials.find_one({"client_id": client_id})
    if doc is None:
        raise XApiError(
            "missing_oauth_credential",
            f"No X OAuth credential on file for client_id={client_id!r}; "
            "the client must complete /api/x/oauth/authorize first.",
        )
    credential = XOAuthCredential(**doc)

    expires_at = credential.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) + REFRESH_SKEW >= expires_at:
        credential = await _refresh(db, credential)

    return credential.access_token


async def post_tweet(
    access_token: str, text: str, media_ids: list[str] | None = None
) -> dict[str, Any]:
    """POST /2/tweets — publish a text post, optionally attaching pre-uploaded media_ids."""
    body: dict[str, Any] = {"text": text}
    if media_ids:
        body["media"] = {"media_ids": media_ids}
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            TWEETS_URL,
            json=body,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code not in (200, 201):
        raise XApiError("publish_failed", f"X publish failed ({resp.status_code}): {resp.text}")
    return resp.json()


async def get_tweet_public_metrics(access_token: str, tweet_id: str) -> dict[str, Any]:
    """GET /2/tweets/:id?tweet.fields=public_metrics — read-only engagement pull."""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{TWEETS_URL}/{tweet_id}",
            params={"tweet.fields": "public_metrics"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code == 404:
        raise XApiError("invalid_platform_post_id", f"No such tweet id={tweet_id!r}.")
    if resp.status_code != 200:
        raise XApiError(
            "metrics_fetch_failed", f"X metrics fetch failed ({resp.status_code}): {resp.text}"
        )

    payload = resp.json()
    data = payload.get("data")
    if not data:
        raise XApiError("invalid_platform_post_id", f"No such tweet id={tweet_id!r}.")
    return data.get("public_metrics", {})
