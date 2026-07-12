from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


Source = Literal["github", "linkup", "posthog"]


class Provenance(BaseModel):
    source: Source
    external_id: str
    raw_record_id: str
    collected_at: datetime
    occurred_at: datetime | None = None
    source_url: str | None = None
    collector_version: str


class RawRecord(BaseModel):
    workspace_id: str
    source: Source
    external_id: str
    kind: str
    payload: Any
    checksum: str
    collected_at: datetime
    occurred_at: datetime | None = None
    source_url: str | None = None
    collector_version: str


class MemoryEvent(BaseModel):
    workspace_id: str
    source: Source
    external_id: str
    event_type: str
    object_type: str
    object_id: str
    occurred_at: datetime
    title: str | None = None
    body: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class MetricObservation(BaseModel):
    workspace_id: str
    source: Source
    external_id: str
    metric_key: str
    value: float
    unit: Literal["count", "percent", "currency", "seconds"] = "count"
    period_start: datetime
    period_end: datetime
    dimensions: dict[str, str | int | float | bool] = Field(default_factory=dict)
    provenance: Provenance


class TrendItem(BaseModel):
    workspace_id: str
    source: Literal["linkup"] = "linkup"
    external_id: str
    query: str
    title: str
    url: HttpUrl
    content: str
    topics: list[str]
    checksum: str
    collected_at: datetime
    publisher: str | None = None
    published_at: datetime | None = None
    provenance: Provenance


class CollectorResult(BaseModel):
    source: Source
    workspace_id: str
    raw_records: int = 0
    events: int = 0
    metrics: int = 0
    trends: int = 0
    started_at: datetime
    completed_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class ProviderConnection(BaseModel):
    workspace_id: str
    provider: Literal["github"] = "github"
    installation_id: int
    account_id: int | None = None
    account_login: str
    repository_selection: Literal["all", "selected"] = "selected"
    repositories: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["active", "suspended", "revoked"] = "active"
    connected_at: datetime
    updated_at: datetime
