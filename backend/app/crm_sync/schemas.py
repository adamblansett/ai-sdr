from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DealStage = Literal[
    "discovery",
    "qualification",
    "proposal",
    "negotiation",
    "closed_won",
    "closed_lost",
]


class CrmDealCreateIn(BaseModel):
    """Payload to create a CRM pipeline deal."""

    account_id: str
    primary_contact_id: str | None = None
    external_id: str | None = Field(default=None, max_length=120)
    name: str = Field(..., min_length=2, max_length=240)
    stage: DealStage = "discovery"
    amount_usd: float = Field(default=0.0, ge=0.0)
    close_date: date | None = None
    owner_email: str = Field(default="manager@acme-sdr.local", max_length=255)
    next_step: str = Field(default="", max_length=2000)
    last_activity_at: datetime | None = None


class HygieneIssueOut(BaseModel):
    """Detected CRM pipeline hygiene deficiency on a deal."""

    code: str
    severity: str
    message: str


class CrmDealOut(BaseModel):
    """Serialized CRM deal with computed hygiene score and issues."""

    id: str
    external_id: str | None
    account_id: str
    primary_contact_id: str | None
    name: str
    stage: str
    amount_usd: float
    close_date: date | None
    owner_email: str
    next_step: str
    last_activity_at: datetime
    hygiene_score: int
    hygiene_issues: list[HygieneIssueOut]
    created_at: datetime
    updated_at: datetime


class HygieneValidateOut(BaseModel):
    """Aggregate pipeline hygiene validation result."""

    deals_checked: int
    deals_flagged: int
    avg_hygiene_score: float
    deals: list[CrmDealOut]


class DuplicateMergeCandidateOut(BaseModel):
    """Serialized duplicate contact pair awaiting HITL merge approval."""

    id: str
    primary_contact_id: str
    duplicate_contact_id: str
    primary_email: str
    duplicate_email: str
    primary_name: str
    duplicate_name: str
    match_reason: str
    confidence: float
    status: str
    approval_id: str | None
    created_at: datetime
    resolved_at: datetime | None


class DeduplicateOut(BaseModel):
    """Result of duplicate contact scan."""

    candidates_created: int
    candidates: list[DuplicateMergeCandidateOut]


class CrmWebhookPayloadIn(BaseModel):
    """Normalized CRM webhook event payload."""

    event_id: str | None = Field(default=None, max_length=160)
    event_type: Literal["contact.upsert", "deal.upsert", "contact.opt_out", "activity.logged"]
    data: dict[str, Any] = Field(default_factory=dict)


class CrmWebhookEventOut(BaseModel):
    """Serialized CRM webhook receipt with idempotency flag."""

    id: str
    idempotency_key: str
    source: str
    event_type: str
    payload_hash: str
    status: str
    result_summary: str
    duplicate_ignored: bool = False
    received_at: datetime
    processed_at: datetime
