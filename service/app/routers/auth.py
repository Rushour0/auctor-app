from __future__ import annotations

import hmac
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .. import session
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Every collection that's scoped by workspace_id — kept in one place so a backfill
# (or any future per-workspace operation) can't silently miss a collection.
_WORKSPACE_SCOPED_COLLECTIONS = (
    "fleet_runs",
    "client_pipelines",
    "fleet_events",
    "workflow_artifacts",
    "approval_requests",
    "content_posts",
    "workflow_triggers",
    "public_deliveries",
    "onboarding_submissions",
    "onboarding_drafts",
)


class CredentialLogin(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


async def _backfill_personal_workspace(db, target_workspace_id: str) -> None:
    """One-time, idempotent migration: the app used to default everything to a
    hardcoded workspace_id "personal" before workspace_id was derived per-operator
    at login. On an operator's first login under the new scheme, move any
    "personal"-workspace data into their real workspace_id — but only if their
    workspace doesn't already have data (never overwrite real per-operator state)."""
    if target_workspace_id == "personal":
        return
    already_has_data = await db.client_pipelines.count_documents(
        {"workspace_id": target_workspace_id}
    )
    if already_has_data:
        return
    has_legacy_data = await db.client_pipelines.count_documents({"workspace_id": "personal"})
    if not has_legacy_data:
        return
    for name in _WORKSPACE_SCOPED_COLLECTIONS:
        await db[name].update_many(
            {"workspace_id": "personal"}, {"$set": {"workspace_id": target_workspace_id}}
        )


async def require_operator(request: Request) -> dict:
    """Resolve the logged-in operator from the session cookie or reject the request."""
    token = request.cookies.get(session.SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        return session.verify_session(token)
    except session.SessionError as exc:
        raise HTTPException(status_code=401, detail="invalid session") from exc


def _require_session_secret() -> None:
    """Every login path (GitHub OAuth or credentials) needs OPERATOR_SESSION_SECRET to
    sign a session/state token — session.create_state/issue_session raise a bare
    SessionError (RuntimeError) if it's unset, which FastAPI turns into an unhandled
    500 rather than a clean error. Call this before any session.* call so a missing
    secret is always a clean 503, never a crash."""
    if not settings.operator_session_secret:
        raise HTTPException(
            status_code=503,
            detail={
                "kind": "missing_session_secret",
                "message": "OPERATOR_SESSION_SECRET is required for login to work.",
            },
        )


@router.get("/github/authorize")
async def authorize() -> RedirectResponse:
    """Start the confidential GitHub OAuth web flow (no PKCE) for operator login."""
    if not settings.github_login_client_id:
        raise HTTPException(
            status_code=412,
            detail={
                "kind": "missing_login_credentials",
                "message": "GITHUB_LOGIN_CLIENT_ID is required",
            },
        )
    _require_session_secret()
    state = session.create_state("/")
    url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": settings.github_login_client_id,
            "redirect_uri": settings.github_login_redirect_uri,
            "state": state,
            "scope": "read:user",
        }
    )
    return RedirectResponse(url, status_code=302)


@router.get("/github/callback")
async def callback(
    request: Request, state: str = Query(...), code: str = Query(...)
) -> RedirectResponse:
    """Handle GitHub's redirect: verify state, exchange the code, set the session cookie."""
    _require_session_secret()
    try:
        session.verify_state(state)
    except session.SessionError as exc:
        raise HTTPException(status_code=400, detail="invalid oauth state") from exc

    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_login_client_id,
                "client_secret": settings.github_login_client_secret,
                "code": code,
                "redirect_uri": settings.github_login_redirect_uri,
            },
        )
        access = token_resp.json().get("access_token")
        if not access:
            raise HTTPException(status_code=400, detail="github token exchange failed")
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/vnd.github+json",
            },
        )
        user = user_resp.json()

    workspace_id = session.workspace_id_for_login(user["login"])
    await _backfill_personal_workspace(request.app.state.db, workspace_id)

    token = session.issue_session(github_login=user["login"], github_id=int(user["id"]))
    resp = RedirectResponse("/", status_code=302)
    _set_session_cookie(resp, token)
    return resp


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        session.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.agency_env != "development",
        max_age=session.SESSION_TTL_SECONDS,
        path="/",
    )


@router.post("/login")
async def login(request: Request, credentials: CredentialLogin) -> JSONResponse:
    """Username/password fallback login — an alternative to GitHub OAuth, same
    session-cookie mechanism either way. Fails loud (503) if the operator hasn't
    configured OPERATOR_LOGIN_USERNAME/PASSWORD; 401 on any mismatch, checked with
    constant-time comparison so response timing can't leak which field was wrong."""
    if not settings.operator_login_username or not settings.operator_login_password:
        raise HTTPException(
            status_code=503,
            detail="Username/password login is not configured on this deployment.",
        )
    _require_session_secret()
    username_ok = hmac.compare_digest(credentials.username, settings.operator_login_username)
    password_ok = hmac.compare_digest(credentials.password, settings.operator_login_password)
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    workspace_id = session.workspace_id_for_login(credentials.username)
    await _backfill_personal_workspace(request.app.state.db, workspace_id)

    # gh_id has no meaning for a credential login; 0 is a stable sentinel the
    # frontend's Operator type (gh_id: number) already accepts without a schema change.
    token = session.issue_session(github_login=credentials.username, github_id=0)
    resp = JSONResponse({"login": credentials.username, "gh_id": 0, "workspace_id": workspace_id})
    _set_session_cookie(resp, token)
    return resp


@router.get("/me")
async def me(operator: dict = Depends(require_operator)) -> dict:
    """Return the currently authenticated operator's identity."""
    return {
        "login": operator["login"],
        "gh_id": operator["gh_id"],
        "workspace_id": operator.get("workspace_id")
        or session.workspace_id_for_login(operator["login"]),
    }


@router.post("/logout")
async def logout() -> JSONResponse:
    """Clear the operator session cookie."""
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(session.SESSION_COOKIE, path="/")
    return resp
