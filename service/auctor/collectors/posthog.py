import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import httpx

from ..config import Settings, get_settings
from ..memory import AuctorMemory, stable_checksum, utc_now
from ..models import CollectorResult, MemoryEvent, MetricObservation, Provenance, RawRecord

VERSION = "posthog-events-v1"


def metric_slug(event_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", event_name.lower()).strip("_") or "unknown"


class PostHogCollector:
    def __init__(
        self,
        memory: AuctorMemory | None = None,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ):
        self.settings = settings or get_settings()
        self.memory = memory or AuctorMemory(self.settings)
        self.client = client or httpx.Client(timeout=60)

    def _api_url(self, path: str) -> str:
        host = self.settings.posthog_host.rstrip("/")
        parsed = urlsplit(host)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("POSTHOG_HOST must be a valid HTTP(S) URL")
        return f"{host}{path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.posthog_personal_api_key}",
            "Content-Type": "application/json",
        }

    def verify_authentication(self, workspace_id: str | None = None) -> dict[str, str | bool]:
        if self.settings.posthog_auth_mode != "personal_api_key":
            raise ValueError("Only POSTHOG_AUTH_MODE=personal_api_key is implemented")
        if not self.settings.posthog_personal_api_key or not self.settings.posthog_project_id:
            raise ValueError("POSTHOG_PERSONAL_API_KEY and POSTHOG_PROJECT_ID are required")

        started_at = utc_now()
        if workspace_id:
            self.memory.save_sync_state(
                workspace_id,
                "posthog",
                "authentication",
                last_started_at=started_at,
                last_error=None,
            )
        try:
            user_response = self.client.get(
                self._api_url("/api/users/@me/"), headers=self._headers()
            )
            user_response.raise_for_status()
            project_response = self.client.get(
                self._api_url(f"/api/projects/{self.settings.posthog_project_id}/"),
                headers=self._headers(),
            )
            project_response.raise_for_status()
            user = user_response.json()
            project = project_response.json()
            result = {
                "authenticated": True,
                "auth_mode": "personal_api_key",
                "host": self.settings.posthog_host.rstrip("/"),
                "project_id": str(project.get("id", self.settings.posthog_project_id)),
                "project_name": str(project.get("name", "")),
                "user_id": str(user.get("uuid") or user.get("id") or ""),
            }
            if workspace_id:
                self.memory.save_sync_state(
                    workspace_id,
                    "posthog",
                    "authentication",
                    last_started_at=started_at,
                    last_completed_at=utc_now(),
                    last_error=None,
                    metadata=result,
                )
            return result
        except Exception as error:
            if workspace_id:
                self.memory.save_sync_state(
                    workspace_id,
                    "posthog",
                    "authentication",
                    last_started_at=started_at,
                    last_error=str(error),
                )
            raise

    @staticmethod
    def _timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    def collect(
        self,
        workspace_id: str,
        since_days: int = 7,
        limit: int = 10_000,
    ) -> CollectorResult:
        self.verify_authentication(workspace_id)
        started_at = utc_now()
        sync_key = "events"
        cursor = self.memory.get_cursor(workspace_id, "posthog", sync_key)
        since = cursor or started_at - timedelta(days=max(1, min(since_days, 365)))
        self.memory.save_sync_state(
            workspace_id, "posthog", sync_key, last_started_at=started_at, last_error=None
        )
        try:
            query = """
                SELECT uuid, event, timestamp, distinct_id, properties
                FROM events
                WHERE timestamp > {since} AND timestamp <= {until}
                ORDER BY timestamp ASC
                LIMIT {limit}
            """.format(
                since=repr(since.isoformat()),
                until=repr(started_at.isoformat()),
                limit=max(1, min(limit, 50_000)),
            )
            endpoint = self._api_url(f"/api/projects/{self.settings.posthog_project_id}/query/")
            response = self.client.post(
                endpoint,
                headers=self._headers(),
                json={"query": {"kind": "HogQLQuery", "query": query}},
            )
            response.raise_for_status()
            payload = response.json()
            columns = payload.get("columns", [])
            rows = [dict(zip(columns, row, strict=False)) for row in payload.get("results", [])]
            counts: Counter[str] = Counter()
            raw_count = event_count = 0
            for row in rows:
                occurred_at = self._timestamp(str(row["timestamp"]))
                external_id = str(row.get("uuid") or stable_checksum(row))
                source_url = f"{self.settings.posthog_host.rstrip('/')}/project/{self.settings.posthog_project_id}/events"
                raw = RawRecord(
                    workspace_id=workspace_id,
                    source="posthog",
                    external_id=external_id,
                    kind="product-event",
                    payload=row,
                    checksum=stable_checksum(row),
                    collected_at=started_at,
                    occurred_at=occurred_at,
                    source_url=source_url,
                    collector_version=VERSION,
                )
                raw_id = self.memory.save_raw(raw)
                provenance = Provenance(
                    source="posthog",
                    external_id=external_id,
                    raw_record_id=raw_id,
                    collected_at=started_at,
                    occurred_at=occurred_at,
                    source_url=source_url,
                    collector_version=VERSION,
                )
                event_name = str(row.get("event") or "unknown")
                self.memory.save_event(
                    MemoryEvent(
                        workspace_id=workspace_id,
                        source="posthog",
                        external_id=external_id,
                        event_type=f"posthog.{event_name}",
                        object_type="product_event",
                        object_id=external_id,
                        title=event_name,
                        occurred_at=occurred_at,
                        attributes={
                            "distinct_id": row.get("distinct_id"),
                            "properties": row.get("properties") or {},
                        },
                        provenance=provenance,
                    )
                )
                counts[event_name] += 1
                raw_count += 1
                event_count += 1

            metric_count = 0
            for event_name, value in counts.items():
                metric_id = f"event-count:{metric_slug(event_name)}:{since.isoformat()}:{started_at.isoformat()}"
                aggregate_payload = {
                    "event": event_name,
                    "count": value,
                    "period_start": since,
                    "period_end": started_at,
                }
                aggregate_raw = RawRecord(
                    workspace_id=workspace_id,
                    source="posthog",
                    external_id=metric_id,
                    kind="event-count",
                    payload=aggregate_payload,
                    checksum=stable_checksum(aggregate_payload),
                    collected_at=started_at,
                    occurred_at=started_at,
                    collector_version=VERSION,
                )
                aggregate_raw_id = self.memory.save_raw(aggregate_raw)
                raw_count += 1
                self.memory.save_metric(
                    MetricObservation(
                        workspace_id=workspace_id,
                        source="posthog",
                        external_id=metric_id,
                        metric_key=f"posthog.event.{metric_slug(event_name)}.count",
                        value=value,
                        period_start=since,
                        period_end=started_at,
                        dimensions={"event": event_name},
                        provenance=Provenance(
                            source="posthog",
                            external_id=metric_id,
                            raw_record_id=aggregate_raw_id,
                            collected_at=started_at,
                            occurred_at=started_at,
                            collector_version=VERSION,
                        ),
                    )
                )
                metric_count += 1

            completed_at = utc_now()
            truncated = len(rows) >= max(1, min(limit, 50_000))
            self.memory.save_sync_state(
                workspace_id,
                "posthog",
                sync_key,
                cursor=cursor if truncated else started_at,
                last_started_at=started_at,
                last_completed_at=completed_at,
                last_error="result limit reached; increase limit before advancing cursor"
                if truncated
                else None,
                metadata={
                    "events": event_count,
                    "metric_series": metric_count,
                    "truncated": truncated,
                },
            )
            return CollectorResult(
                source="posthog",
                workspace_id=workspace_id,
                raw_records=raw_count,
                events=event_count,
                metrics=metric_count,
                started_at=started_at,
                completed_at=completed_at,
                details={"truncated": truncated, "checked_from": since},
            )
        except Exception as error:
            self.memory.save_sync_state(
                workspace_id,
                "posthog",
                sync_key,
                last_started_at=started_at,
                last_error=str(error),
            )
            raise
