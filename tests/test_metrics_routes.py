"""Exercises the /api/metrics + /api/metrics/export read endpoints in isolation.

The router is mounted on a standalone app (not service.app.main) so these tests do
not depend on the router being wired into main.py, and Mongo is stubbed out entirely.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# The aggregations helper is a sibling unit; skip cleanly if it has not landed yet
# rather than hard-failing collection for the whole suite.
pytest.importorskip("service.app.metrics_aggregations")

from service.app.routers import metrics as metrics_router  # noqa: E402


class _FakeStore:
    db = object()

    def ensure_indexes(self) -> None:  # pragma: no cover - trivial stub
        return None


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(metrics_router.router)
    return app


@pytest.fixture(autouse=True)
def _stub_store(monkeypatch):
    monkeypatch.setattr(metrics_router, "_workflow_store", lambda: _FakeStore())


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_metrics_returns_aggregation_payload(monkeypatch):
    captured: dict = {}

    def fake_build(db, workspace_id, platform):
        captured["args"] = (db, workspace_id, platform)
        return {"workspace_id": workspace_id, "cost_by_status": {}, "avg_per_run_usd": 0.0}

    monkeypatch.setattr(metrics_router, "build_metrics_payload", fake_build)

    async with await _client(_build_app()) as client:
        resp = await client.get("/api/metrics", params={"workspace_id": "workspace-1"})

    assert resp.status_code == 200
    assert resp.json()["workspace_id"] == "workspace-1"
    assert captured["args"][1] == "workspace-1"
    assert captured["args"][2] is None


@pytest.mark.asyncio
async def test_metrics_forwards_platform_filter(monkeypatch):
    monkeypatch.setattr(
        metrics_router,
        "build_metrics_payload",
        lambda db, workspace_id, platform: {"platform": platform},
    )

    async with await _client(_build_app()) as client:
        resp = await client.get(
            "/api/metrics", params={"workspace_id": "workspace-1", "platform": "x"}
        )

    assert resp.status_code == 200
    assert resp.json()["platform"] == "x"


@pytest.mark.asyncio
async def test_export_wraps_payload_in_versioned_envelope(monkeypatch):
    monkeypatch.setattr(
        metrics_router,
        "build_metrics_payload",
        lambda db, workspace_id, platform: {"avg_per_run_usd": 1.23},
    )

    async with await _client(_build_app()) as client:
        resp = await client.get("/api/metrics/export", params={"workspace_id": "workspace-1"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["schema"] == "auctor.metrics.v1"
    assert body["payload"] == {"avg_per_run_usd": 1.23}


@pytest.mark.asyncio
async def test_blank_workspace_id_rejected(monkeypatch):
    monkeypatch.setattr(
        metrics_router, "build_metrics_payload", lambda *_: pytest.fail("should not aggregate")
    )

    async with await _client(_build_app()) as client:
        # whitespace passes Query min_length but must be rejected by the explicit guard
        resp = await client.get("/api/metrics", params={"workspace_id": "   "})

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_missing_workspace_id_is_validation_error():
    async with await _client(_build_app()) as client:
        resp = await client.get("/api/metrics")

    assert resp.status_code == 422
