import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

from .config import Settings, get_settings
from .models import MemoryEvent, MetricObservation, ProviderConnection, RawRecord, TrendItem


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stable_checksum(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class AuctorMemory:
    def __init__(self, settings: Settings | None = None, database: Database | None = None):
        self.settings = settings or get_settings()
        self._client: MongoClient | None = None
        if database is not None:
            self.db = database
        else:
            self._client = MongoClient(self.settings.mongodb_uri)
            self.db = self._client[self.settings.mongodb_db]

    def ensure_indexes(self) -> None:
        self.db.raw_records.create_index(
            [("workspace_id", ASCENDING), ("source", ASCENDING), ("external_id", ASCENDING)],
            unique=True,
        )
        self.db.events.create_index(
            [("workspace_id", ASCENDING), ("source", ASCENDING), ("external_id", ASCENDING)],
            unique=True,
        )
        self.db.events.create_index(
            [("workspace_id", ASCENDING), ("occurred_at", DESCENDING), ("event_type", ASCENDING)]
        )
        self.db.metric_observations.create_index(
            [("workspace_id", ASCENDING), ("source", ASCENDING), ("external_id", ASCENDING)],
            unique=True,
        )
        self.db.metric_observations.create_index(
            [("workspace_id", ASCENDING), ("metric_key", ASCENDING), ("period_start", DESCENDING)]
        )
        self.db.trend_items.create_index(
            [("workspace_id", ASCENDING), ("external_id", ASCENDING)], unique=True
        )
        self.db.sync_states.create_index(
            [("workspace_id", ASCENDING), ("source", ASCENDING), ("key", ASCENDING)],
            unique=True,
        )
        self.db.provider_connections.create_index(
            [("workspace_id", ASCENDING), ("provider", ASCENDING)], unique=True
        )
        self.db.webhook_deliveries.create_index("delivery_id", unique=True)

    @staticmethod
    def _document(model: Any) -> dict[str, Any]:
        return model.model_dump(mode="python")

    def save_raw(self, record: RawRecord) -> str:
        key = {
            "workspace_id": record.workspace_id,
            "source": record.source,
            "external_id": record.external_id,
        }
        self.db.raw_records.update_one(
            key,
            {"$set": self._document(record), "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )
        return f"{record.workspace_id}:{record.source}:{record.external_id}"

    def save_event(self, event: MemoryEvent) -> None:
        key = {
            "workspace_id": event.workspace_id,
            "source": event.source,
            "external_id": event.external_id,
        }
        self.db.events.update_one(
            key,
            {"$set": self._document(event), "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )

    def save_metric(self, metric: MetricObservation) -> None:
        key = {
            "workspace_id": metric.workspace_id,
            "source": metric.source,
            "external_id": metric.external_id,
        }
        self.db.metric_observations.update_one(
            key,
            {"$set": self._document(metric), "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )

    def save_trend(self, trend: TrendItem) -> None:
        key = {"workspace_id": trend.workspace_id, "external_id": trend.external_id}
        self.db.trend_items.update_one(
            key,
            {"$set": self._document(trend), "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )

    def get_cursor(self, workspace_id: str, source: str, key: str) -> datetime | None:
        state = self.db.sync_states.find_one(
            {"workspace_id": workspace_id, "source": source, "key": key}
        )
        cursor = state.get("cursor") if state else None
        if isinstance(cursor, datetime):
            return cursor.replace(tzinfo=cursor.tzinfo or timezone.utc)
        if isinstance(cursor, str):
            return datetime.fromisoformat(cursor.replace("Z", "+00:00"))
        return None

    def save_sync_state(self, workspace_id: str, source: str, key: str, **values: Any) -> None:
        identity = {"workspace_id": workspace_id, "source": source, "key": key}
        self.db.sync_states.update_one(
            identity,
            {"$set": {**identity, **values}, "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )

    def status(self, workspace_id: str) -> dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "counts": {
                "raw_records": self.db.raw_records.count_documents({"workspace_id": workspace_id}),
                "events": self.db.events.count_documents({"workspace_id": workspace_id}),
                "metrics": self.db.metric_observations.count_documents(
                    {"workspace_id": workspace_id}
                ),
                "trends": self.db.trend_items.count_documents({"workspace_id": workspace_id}),
            },
            "sync_states": list(
                self.db.sync_states.find({"workspace_id": workspace_id}, {"_id": 0}).sort(
                    "last_started_at", DESCENDING
                )
            ),
        }

    def save_provider_connection(self, connection: ProviderConnection) -> None:
        key = {"workspace_id": connection.workspace_id, "provider": connection.provider}
        self.db.provider_connections.update_one(
            key,
            {"$set": self._document(connection), "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )

    def get_provider_connection(self, workspace_id: str, provider: str) -> dict[str, Any] | None:
        return self.db.provider_connections.find_one(
            {"workspace_id": workspace_id, "provider": provider}, {"_id": 0}
        )

    def delete_provider_connection(self, workspace_id: str, provider: str) -> None:
        self.db.provider_connections.delete_one(
            {"workspace_id": workspace_id, "provider": provider}
        )

    def record_webhook_delivery(self, delivery_id: str, event: str) -> bool:
        result = self.db.webhook_deliveries.update_one(
            {"delivery_id": delivery_id},
            {
                "$setOnInsert": {
                    "delivery_id": delivery_id,
                    "event": event,
                    "received_at": utc_now(),
                }
            },
            upsert=True,
        )
        return result.upserted_id is not None
