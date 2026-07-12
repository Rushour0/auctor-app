"""Confirms the /api/x/oauth router is wired into the app without breaking existing routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from service.app.main import app


@pytest.mark.asyncio
async def test_health_and_version_still_work():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            health = await client.get("/health")
            version = await client.get("/version")
    assert health.status_code == 200
    assert version.status_code == 200


@pytest.mark.asyncio
async def test_authorize_route_fails_loud_without_app_credentials(monkeypatch):
    from service.app import x_integration

    monkeypatch.setattr(x_integration.settings, "twitter_api_key", "")
    monkeypatch.setattr(x_integration.settings, "twitter_api_secret", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get(
                "/api/x/oauth/authorize", params={"client_id": "client_a"}, follow_redirects=False
            )
    assert resp.status_code == 412
    assert resp.json()["detail"]["kind"] == "missing_api_key"
