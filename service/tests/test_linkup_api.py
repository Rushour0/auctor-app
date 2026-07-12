from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient

from service.app import main
from service.auctor.collectors.linkup import LinkupAPIError
from service.auctor.models import CollectorResult


class FakeLinkupCollector:
    def verify_authentication(self, workspace_id: str) -> dict:
        assert workspace_id == "workspace-1"
        return {"authenticated": True, "credits_balance": 12.5}

    def collect(self, **values: object) -> CollectorResult:
        assert values["workspace_id"] == "workspace-1"
        assert values["topics"] == ["AI agents"]
        assert values["depth"] == "standard"
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        return CollectorResult(
            source="linkup",
            workspace_id="workspace-1",
            raw_records=2,
            trends=2,
            started_at=now,
            completed_at=now,
        )


def test_linkup_routes_verify_and_sync(monkeypatch: object) -> None:
    monkeypatch.setattr(main, "LinkupCollector", FakeLinkupCollector)  # type: ignore[attr-defined]
    with TestClient(main.app) as client:
        verify = client.post(
            "/api/integrations/linkup/verify", params={"workspace_id": "workspace-1"}
        )
        sync = client.post(
            "/api/integrations/linkup/sync",
            json={"workspace_id": "workspace-1", "topics": ["AI agents"]},
        )

    assert verify.status_code == 200
    assert verify.json() == {"authenticated": True, "credits_balance": 12.5}
    assert sync.status_code == 200
    assert sync.json()["trends"] == 2


def test_linkup_route_returns_structured_provider_error(monkeypatch: object) -> None:
    response = httpx.Response(
        401,
        json={"error": {"code": "AUTHENTICATION_ERROR", "message": "Invalid API key"}},
    )

    class FailingCollector:
        def verify_authentication(self, workspace_id: str) -> dict:
            raise LinkupAPIError(response)

    monkeypatch.setattr(main, "LinkupCollector", FailingCollector)  # type: ignore[attr-defined]
    with TestClient(main.app) as client:
        result = client.post(
            "/api/integrations/linkup/verify", params={"workspace_id": "workspace-1"}
        )

    assert result.status_code == 401
    assert result.json()["detail"]["code"] == "AUTHENTICATION_ERROR"
