import pytest
from httpx import ASGITransport, AsyncClient

from service.app.main import app


@pytest.mark.asyncio
async def test_version_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/version")
    assert resp.status_code == 200
    assert resp.json()["auctor"]
