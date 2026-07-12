from datetime import datetime, timezone
from typing import Any

import httpx

from service.auctor.collectors.github import GitHubCollector
from service.auctor.collectors.linkup import LinkupAPIError, LinkupCollector, canonical_url
from service.auctor.collectors.posthog import PostHogCollector, metric_slug
from service.auctor.config import Settings


class FakeMemory:
    def __init__(self, cursor: datetime | None = None):
        self.cursor = cursor
        self.raw: list[Any] = []
        self.events: list[Any] = []
        self.metrics: list[Any] = []
        self.trends: list[Any] = []
        self.states: list[dict[str, Any]] = []

    def get_cursor(self, *_: Any) -> datetime | None:
        return self.cursor

    def save_raw(self, record: Any) -> str:
        self.raw.append(record)
        return f"raw:{record.external_id}"

    def save_event(self, event: Any) -> None:
        self.events.append(event)

    def save_metric(self, metric: Any) -> None:
        self.metrics.append(metric)

    def save_trend(self, trend: Any) -> None:
        self.trends.append(trend)

    def save_sync_state(self, workspace_id: str, source: str, key: str, **values: Any) -> None:
        self.states.append({"workspace_id": workspace_id, "source": source, "key": key, **values})


def settings(**overrides: Any) -> Settings:
    return Settings(
        mongodb_uri="mongodb://unused",
        github_token="github-token",
        linkup_api_key="linkup-token",
        posthog_project_id="123",
        posthog_personal_api_key="posthog-token",
        **overrides,
    )


def test_github_collects_only_new_main_merges() -> None:
    cursor = datetime(2026, 7, 10, tzinfo=timezone.utc)
    memory = FakeMemory(cursor)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/user":
            return httpx.Response(200, json={"login": "Rushour0"})
        if path.endswith("/pulls"):
            assert request.url.params["base"] == "main"
            return httpx.Response(
                200,
                json=[
                    {"number": 9, "merged_at": "2026-07-11T10:00:00Z"},
                    {"number": 8, "merged_at": "2026-07-09T10:00:00Z"},
                    {"number": 7, "merged_at": None},
                ],
            )
        if path.endswith("/pulls/9"):
            return httpx.Response(
                200,
                json={
                    "number": 9,
                    "title": "Add source collectors",
                    "body": "Collect real signals.",
                    "merged_at": "2026-07-11T10:00:00Z",
                    "html_url": "https://github.com/Rushour0/auctor-app/pull/9",
                    "head": {"ref": "collectors"},
                    "user": {"login": "Rushour0"},
                    "merge_commit_sha": "merge-sha",
                    "additions": 12,
                    "deletions": 3,
                    "changed_files": 1,
                },
            )
        if path.endswith("/pulls/9/files"):
            return httpx.Response(
                200,
                json=[{"filename": "service/app.py", "status": "added", "patch": "+hello"}],
            )
        if path.endswith("/pulls/9/commits"):
            return httpx.Response(
                200,
                json=[
                    {
                        "sha": "abc",
                        "commit": {
                            "message": "Add collector",
                            "author": {"date": "2026-07-11T09:00:00Z"},
                            "committer": {"date": "2026-07-11T09:01:00Z"},
                        },
                    }
                ],
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com")
    result = GitHubCollector(memory=memory, settings=settings(), client=client).collect(
        "kriti-personal", repositories=["Rushour0/auctor-app"]
    )

    assert result.events == 1
    assert len(memory.events) == 1
    event = memory.events[0]
    assert event.title == "Add source collectors"
    assert event.occurred_at == datetime(2026, 7, 11, 10, tzinfo=timezone.utc)
    assert event.attributes["commit_messages"][0]["message"] == "Add collector"
    assert event.attributes["files"][0]["patch"] == "+hello"
    assert memory.states[-1]["cursor"] is not None


def test_posthog_stores_events_and_counts() -> None:
    memory = FakeMemory(datetime(2026, 7, 10, tzinfo=timezone.utc))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer posthog-token"
        if request.method == "GET" and request.url.path == "/api/users/@me/":
            return httpx.Response(200, json={"uuid": "user-1"})
        if request.method == "GET" and request.url.path == "/api/projects/123/":
            return httpx.Response(200, json={"id": 123, "name": "Auctor"})
        body = __import__("json").loads(request.content)
        assert body["query"]["kind"] == "HogQLQuery"
        return httpx.Response(
            200,
            json={
                "columns": ["uuid", "event", "timestamp", "distinct_id", "properties"],
                "results": [
                    ["one", "$pageview", "2026-07-11T10:00:00Z", "person-1", {"$current_url": "/"}],
                    [
                        "two",
                        "$pageview",
                        "2026-07-11T11:00:00Z",
                        "person-2",
                        {"$current_url": "/pricing"},
                    ],
                    ["three", "user_signed_up", "2026-07-11T12:00:00Z", "person-2", {}],
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = PostHogCollector(memory=memory, settings=settings(), client=client).collect(
        "kriti-personal"
    )

    assert result.events == 3
    assert result.metrics == 2
    values = {metric.metric_key: metric.value for metric in memory.metrics}
    assert values["posthog.event.pageview.count"] == 2
    assert values["posthog.event.user_signed_up.count"] == 1


def test_posthog_authentication_verifies_user_and_project() -> None:
    memory = FakeMemory()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/users/@me/":
            return httpx.Response(200, json={"uuid": "user-1", "email": "private@example.com"})
        if request.url.path == "/api/projects/123/":
            return httpx.Response(200, json={"id": 123, "name": "Auctor"})
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = PostHogCollector(
        memory=memory, settings=settings(), client=client
    ).verify_authentication("kriti-personal")

    assert result == {
        "authenticated": True,
        "auth_mode": "personal_api_key",
        "host": "https://us.posthog.com",
        "project_id": "123",
        "project_name": "Auctor",
        "user_id": "user-1",
    }
    assert "email" not in result
    assert memory.states[-1]["last_error"] is None


def test_posthog_authentication_records_failure_without_secret() -> None:
    memory = FakeMemory()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"detail": "Invalid Personal API key"})
        )
    )
    collector = PostHogCollector(memory=memory, settings=settings(), client=client)

    try:
        collector.verify_authentication("kriti-personal")
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("Expected authentication failure")

    assert memory.states[-1]["last_error"]
    assert "posthog-token" not in memory.states[-1]["last_error"]


def test_linkup_authentication_and_incremental_search() -> None:
    memory = FakeMemory(datetime(2026, 7, 10, tzinfo=timezone.utc))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer linkup-token"
        if request.method == "GET" and request.url.path == "/v1/credits/balance":
            return httpx.Response(200, json={"balance": 42.5})
        if request.method == "POST" and request.url.path == "/v1/search":
            body = __import__("json").loads(request.content)
            assert body["fromDate"] == "2026-07-10"
            assert body["includeDomains"] == ["openai.com"]
            assert body["excludeDomains"] == ["wikipedia.org"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Agent update",
                            "url": "https://openai.com/news/agents?utm_source=test",
                            "content": "A primary-source product update.",
                            "date": "2026-07-11",
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = LinkupCollector(memory=memory, settings=settings(), client=client)
    auth = collector.verify_authentication("kriti-personal")
    result = collector.collect(
        "kriti-personal",
        topics=["AI agents"],
        include_domains=["openai.com"],
        exclude_domains=["wikipedia.org"],
    )

    assert auth == {"authenticated": True, "credits_balance": 42.5}
    assert result.trends == 1
    assert str(memory.trends[0].url) == "https://openai.com/news/agents"
    assert memory.states[-1]["cursor"] is not None


def test_linkup_authentication_error_is_structured_and_secret_safe() -> None:
    memory = FakeMemory()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401,
                json={
                    "statusCode": 401,
                    "error": {"code": "AUTHENTICATION_ERROR", "message": "Invalid API key"},
                },
            )
        )
    )

    try:
        LinkupCollector(memory=memory, settings=settings(), client=client).verify_authentication(
            "kriti-personal"
        )
    except LinkupAPIError as error:
        assert error.code == "AUTHENTICATION_ERROR"
        assert error.status_code == 401
        assert "linkup-token" not in str(error)
    else:
        raise AssertionError("Expected Linkup authentication failure")


def test_url_and_metric_normalization() -> None:
    assert (
        canonical_url("https://Example.com/news/?utm_source=x&id=2#top")
        == "https://example.com/news?id=2"
    )
    assert metric_slug("$pageview") == "pageview"
