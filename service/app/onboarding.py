from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from service.auctor.workflow import ClientIntake, FleetIntake


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IdentityDetails(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    job_title: str = Field(min_length=2, max_length=120)
    company: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=120)
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=80)
    short_bio: str = Field(default="", max_length=600)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class SourceDetails(BaseModel):
    linkedin_url: str = Field(min_length=1, max_length=500)
    website_url: str = Field(default="", max_length=500)
    resume_url: str = Field(default="", max_length=500)
    github_url: str = Field(default="", max_length=500)
    other_urls: list[str] = Field(default_factory=list, max_length=10)


class PositioningDetails(BaseModel):
    primary_goal: Literal[
        "build_authority", "attract_customers", "find_opportunities", "launch_product", "other"
    ]
    goal_detail: str = Field(default="", max_length=600)
    audience: list[str] = Field(min_length=1, max_length=8)
    known_for: str = Field(min_length=10, max_length=500)
    call_to_action: str = Field(default="", max_length=240)
    content_topics: list[str] = Field(min_length=1, max_length=10)


class ProofPoint(BaseModel):
    claim: str = Field(min_length=3, max_length=500)
    source_url: str = Field(default="", max_length=500)


class VoiceDetails(BaseModel):
    writing_samples: list[str] = Field(default_factory=list, max_length=8)
    tone_words: list[str] = Field(default_factory=list, max_length=8)
    phrases_to_use: list[str] = Field(default_factory=list, max_length=15)
    phrases_to_avoid: list[str] = Field(default_factory=list, max_length=15)
    notes: str = Field(default="", max_length=1000)


class PublishingDetails(BaseModel):
    platforms: list[Literal["x", "linkedin"]] = Field(default_factory=lambda: ["x"])
    posts_per_week: int = Field(default=3, ge=1, le=21)
    approval_channel: Literal["whatsapp", "web"] = "whatsapp"
    whatsapp_number: str = Field(default="", max_length=40)
    topics_to_avoid: list[str] = Field(default_factory=list, max_length=15)

    @model_validator(mode="after")
    def whatsapp_is_present_when_selected(self) -> "PublishingDetails":
        if self.approval_channel == "whatsapp" and len(self.whatsapp_number.strip()) < 7:
            raise ValueError("WhatsApp number is required for WhatsApp approvals")
        return self


class ConsentDetails(BaseModel):
    research_public_sources: bool = False
    store_brand_profile: bool = False
    require_approval_before_publish: bool = True


class OnboardingSubmission(BaseModel):
    workspace_id: str = Field(default="personal", min_length=1, max_length=120)
    client_id: str | None = Field(default=None, max_length=120)
    identity: IdentityDetails
    sources: SourceDetails
    positioning: PositioningDetails
    proof_points: list[ProofPoint] = Field(default_factory=list, max_length=20)
    voice: VoiceDetails = Field(default_factory=VoiceDetails)
    publishing: PublishingDetails = Field(default_factory=PublishingDetails)
    consent: ConsentDetails

    @model_validator(mode="after")
    def required_consent(self) -> "OnboardingSubmission":
        if not self.consent.research_public_sources or not self.consent.store_brand_profile:
            raise ValueError("Research and brand-profile consent are required to begin")
        if not self.consent.require_approval_before_publish:
            raise ValueError("Auctor always requires approval before publishing")
        return self

    def identifiers(self) -> tuple[str, str]:
        client_id = self.client_id or f"client_{uuid4().hex[:12]}"
        return client_id, f"fleet_{uuid4().hex[:12]}"

    def to_fleet_intake(self, client_id: str, fleet_id: str) -> FleetIntake:
        context = self.model_dump(mode="python", exclude={"workspace_id", "client_id"})
        return FleetIntake(
            workspace_id=self.workspace_id,
            fleet_id=fleet_id,
            request=self.positioning.goal_detail or self.positioning.primary_goal,
            clients=[
                ClientIntake(
                    client_id=client_id,
                    name=self.identity.full_name,
                    linkedin_url=self.sources.linkedin_url,
                    site_url=self.sources.website_url or None,
                    resume_url=self.sources.resume_url or None,
                    audience=self.positioning.audience,
                    self_reported_context=context,
                )
            ],
        )


class OnboardingDraft(BaseModel):
    draft_id: str | None = None
    workspace_id: str = Field(default="personal", min_length=1, max_length=120)
    payload: dict = Field(default_factory=dict)
