from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


class ClientStatus(StrEnum):
    QUEUED = "queued"
    RESEARCHING = "researching"
    STRATEGIZING = "strategizing"
    WRITING = "writing"
    VOICING = "voicing"
    BUILDING = "building"
    QA = "qa"
    REPAIRING = "repairing"
    AWAITING_APPROVAL = "awaiting_approval"
    DEPLOYING = "deploying"
    LIVE = "live"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContentLoopMode(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class ContentPostStatus(StrEnum):
    IDEATION = "ideation"
    DRAFTING = "drafting"
    QA = "qa"
    REPAIRING = "repairing"
    AWAITING_APPROVAL = "awaiting_approval"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    ANALYZING = "analyzing"
    LEARNED = "learned"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    provider: str | None = None
    model: str | None = None

    def add(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            latency_ms=self.latency_ms + other.latency_ms,
        )


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: f"artifact_{uuid4().hex[:12]}")
    type: str
    title: str
    uri: str
    status: Literal["draft", "ready", "published", "failed"] = "ready"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlatformPublishStatus(BaseModel):
    platform: Literal["x", "linkedin"]
    status: Literal["pending", "published", "failed"] = "pending"
    platform_post_id: str | None = None
    published_at: datetime | None = None
    error_message: str | None = None


class ClientBrandMemory(BaseModel):
    client_id: str
    one_liner: str = ""
    brand_pillars: list[dict[str, Any]] = Field(default_factory=list)
    icp: dict[str, Any] = Field(default_factory=dict)
    tone_profile: dict[str, Any] = Field(default_factory=dict)
    voice_profile_ref: str | None = None
    content_pillars: list[str] = Field(default_factory=list)
    proof_points: list[dict[str, Any]] = Field(default_factory=list)
    cta: dict[str, Any] = Field(default_factory=dict)
    career_history: list[dict[str, Any]] = Field(default_factory=list)
    achievements: list[dict[str, Any]] = Field(default_factory=list)
    version: int = 1
    drift_incidents: list[dict[str, Any]] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=now)


class ContentPost(BaseModel):
    id: str = Field(default_factory=lambda: f"post_{uuid4().hex[:12]}")
    client_id: str
    fleet_id: str
    topic: str = ""
    post_type: str | None = None
    format: Literal["text", "text+image", "text+video"] = "text"
    status: ContentPostStatus = ContentPostStatus.IDEATION
    draft: str | None = None
    based_on_memory_version: int | None = None
    claim_refs: list[str] = Field(default_factory=list)
    platforms: list[PlatformPublishStatus] = Field(default_factory=list)
    retry_count: int = 0
    usage: Usage = Field(default_factory=Usage)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class EngagementEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"eng_{uuid4().hex[:12]}")
    client_id: str
    post_id: str
    platform: Literal["x", "linkedin"]
    impressions: int = 0
    reactions: int = 0
    comments: int = 0
    reshares: int = 0
    captured_at: datetime = Field(default_factory=now)


class ClientPipeline(BaseModel):
    client_id: str
    fleet_id: str
    name: str
    linkedin_url: str | None = None
    language: str = "en"
    status: ClientStatus = ClientStatus.QUEUED
    current_specialist: str | None = None
    retry_count: int = 0
    summary: str | None = None
    live_url: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    content_loop_mode: ContentLoopMode = ContentLoopMode.STOPPED
    content_cadence_per_week: int = 3
    next_content_check_at: datetime | None = None
    last_release_seen: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

    def can_retry(self, max_attempts: int) -> bool:
        return self.retry_count < max_attempts


class FleetRun(BaseModel):
    id: str = Field(default_factory=lambda: f"fleet_{uuid4().hex[:12]}")
    workspace_id: str
    request: str | None = None
    clients: list[ClientPipeline] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class XOAuthState(BaseModel):
    """Short-lived PKCE handshake state for one client's X authorize-redirect round trip.

    Stored in the ``x_oauth_states`` collection, keyed by ``state`` (the CSRF/state token echoed
    back on the callback), and deleted once the callback consumes it.
    """

    state: str = Field(default_factory=lambda: uuid4().hex)
    client_id: str
    code_verifier: str
    created_at: datetime = Field(default_factory=now)


class XOAuthCredential(BaseModel):
    """Per-client X (Twitter) OAuth 2.0 user-context token set.

    Stored in the ``x_oauth_credentials`` collection, one document per ``client_id`` — never
    shared across clients (fleet isolation). ``access_token`` is short-lived (~2h);
    ``refresh_token`` rotates on every use per X's refresh-token-rotation behavior.
    """

    client_id: str
    x_user_id: str | None = None
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str = "tweet.read tweet.write users.read offline.access"
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"approval_{uuid4().hex[:12]}")
    client_id: str
    post_id: str | None = None
    question: str
    channel: Literal["whatsapp", "web"] = "whatsapp"
    risk: Literal["low", "medium", "high"] = "medium"
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime = Field(default_factory=now)
