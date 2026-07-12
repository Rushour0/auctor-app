from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from .. import x_integration

router = APIRouter(prefix="/api/x/oauth", tags=["x-oauth"])


@router.get("/authorize")
async def authorize(request: Request, client_id: str = Query(...)) -> RedirectResponse:
    """Start the per-client X OAuth 2.0 Authorization Code + PKCE handshake."""
    try:
        url = await x_integration.start_authorize(request.app.state.db, client_id)
    except x_integration.XApiError as exc:
        raise HTTPException(
            status_code=412, detail={"kind": exc.kind, "message": exc.message}
        ) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(request: Request, state: str = Query(...), code: str = Query(...)) -> dict:
    """Handle X's redirect back: exchange the code for tokens and persist them."""
    try:
        credential = await x_integration.handle_callback(
            request.app.state.db, state=state, code=code
        )
    except x_integration.XApiError as exc:
        raise HTTPException(
            status_code=400, detail={"kind": exc.kind, "message": exc.message}
        ) from exc
    return {
        "client_id": credential.client_id,
        "connected": True,
        "expires_at": credential.expires_at,
    }
