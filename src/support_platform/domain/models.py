"""Canonical domain + API models. These are *our* shapes; upstream payloads are
translated into them by ``upstreams.translators`` (anti-corruption layer) and never
leak to consumers."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CaseStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_CUSTOMER = "pending_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


ACTIVE_STATUSES = frozenset({CaseStatus.OPEN, CaseStatus.IN_PROGRESS, CaseStatus.PENDING_CUSTOMER})


class SupportTier(StrEnum):
    PLATINUM = "Platinum"
    GOLD = "Gold"
    SILVER = "Silver"
    STANDARD = "Standard"


class EscalationReason(StrEnum):
    CUSTOMER_IMPACT = "customer_impact"
    SLA_BREACH_RISK = "sla_breach_risk"
    SECURITY_INCIDENT = "security_incident"
    EXECUTIVE_REQUEST = "executive_request"
    OTHER = "other"


class CommentVisibility(StrEnum):
    INTERNAL = "internal"
    PUBLIC = "public"


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


# ---- domain (internal) ------------------------------------------------------------------

class Comment(_Model):
    id: str
    author: str
    body: str
    created_at: datetime
    visibility: CommentVisibility = CommentVisibility.INTERNAL


class Escalation(_Model):
    level: int = 0
    target_team: str | None = None
    reason: str | None = None


class Case(_Model):
    id: str
    account_id: str
    priority: Priority
    status: CaseStatus
    subject: str
    opened_at: datetime
    updated_at: datetime
    version: int
    escalation: Escalation = Field(default_factory=Escalation)
    comment_count: int = 0
    comments: list[Comment] | None = None

    @property
    def etag(self) -> str:
        return f'"v{self.version}"'


class Account(_Model):
    id: str
    name: str
    support_tier: SupportTier
    contract_end: date
    arr_usd: int | None = None
    primary_contact_email: str | None = None


class UsageMonth(_Model):
    month: str
    protected_tb: float
    api_calls: int
    active_users: int


# ---- API request bodies -----------------------------------------------------------------

class CommentCreate(_Model):
    body: str = Field(min_length=1, max_length=4000)
    visibility: CommentVisibility = CommentVisibility.INTERNAL

    @field_validator("body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain text, not only whitespace")
        return value


class EscalateRequest(_Model):
    reason: EscalationReason
    note: str | None = Field(default=None, max_length=500)


class WebhookSubscriptionCreate(_Model):
    url: str = Field(min_length=10, max_length=2048, pattern=r"^https?://")
    event_types: list[str] = Field(alias="eventTypes", min_length=1, max_length=10)
    description: str | None = Field(default=None, max_length=200)

