from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import session
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def require_operator(request: Request) -> dict:
    """Resolve the logged-in operator from the session cookie or reject the request."""
    token = request.cookies.get(session.SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        return session.verify_session(token)
    except session.SessionError as exc:
        raise HTTPException(status_code=401, detail="invalid session") from exc


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
async def callback(state: str = Query(...), code: str = Query(...)) -> RedirectResponse:
    """Handle GitHub's redirect: verify state, exchange the code, set the session cookie."""
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

    token = session.issue_session(github_login=user["login"], github_id=int(user["id"]))
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        session.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.agency_env != "development",
        max_age=session.SESSION_TTL_SECONDS,
        path="/",
    )
    return resp


@router.get("/me")
async def me(operator: dict = Depends(require_operator)) -> dict:
    """Return the currently authenticated operator's identity."""
    return {"login": operator["login"], "gh_id": operator["gh_id"]}


@router.post("/logout")
async def logout() -> JSONResponse:
    """Clear the operator session cookie."""
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(session.SESSION_COOKIE, path="/")
    return resp
