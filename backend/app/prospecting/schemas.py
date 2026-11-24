from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AccountCreateIn(BaseModel):
    """Payload to create a target B2B account."""

    name: str = Field(..., min_length=1, max_length=200)
    domain: str = Field(..., min_length=3, max_length=200)
    industry: str = Field(default="", max_length=120)
    employee_count: int = Field(default=0, ge=0, le=1_000_000)
    annual_revenue_usd: float = Field(default=0.0, ge=0.0)
    headquarters: str = Field(default="", max_length=200)
    tech_stack: list[str] = Field(default_factory=list)
    research_summary: str = Field(default="", max_length=5000)


class AccountOut(BaseModel):
    """Serialized target B2B account."""

    id: str
    name: str
    domain: str
    industry: str
    employee_count: int
    annual_revenue_usd: float
    headquarters: str
    tech_stack: list[str]
    icp_fit_score: int
    signal_score: int
    research_summary: str
    status: str
    created_at: datetime
    updated_at: datetime


class SignalCreateIn(BaseModel):
    """Payload to record a public buying signal for an account."""

    signal_type: str = Field(..., min_length=2, max_length=64)
    title: str = Field(..., min_length=2, max_length=240)
    summary: str = Field(default="", max_length=3000)
    evidence_excerpt: str = Field(default="", max_length=3000)
    source_url: str = Field(default="", max_length=500)
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    weight: int = Field(default=20, ge=1, le=100)
    observed_at: datetime | None = None
    verified: bool = True


class SignalOut(BaseModel):
    """Serialized public account signal."""

    id: str
    account_id: str
    signal_type: str
    title: str
    summary: str
    evidence_excerpt: str
    source_url: str
    confidence: float
    weight: int
    observed_at: datetime
    verified: bool
    created_at: datetime


class AccountResearchOut(BaseModel):
    """Result of AI account research synthesis."""

    account: AccountOut
    llm_provider: str
    llm_model: str
    pii_redacted: bool


class ContactCreateIn(BaseModel):
    """Payload to create a prospect contact under an account."""

    account_id: str
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=255)
    title: str = Field(default="", max_length=160)
    seniority: Literal["c_level", "vp", "director", "manager", "ic"] | None = None
    department: str = Field(default="", max_length=80)
    phone: str = Field(default="", max_length=40)
    linkedin_url: str = Field(default="", max_length=300)
    crm_external_id: str | None = Field(default=None, max_length=120)


class ContactOut(BaseModel):
    """Serialized contact with live suppression posture."""

    id: str
    account_id: str
    first_name: str
    last_name: str
    email: str
    title: str
    seniority: str
    department: str
    phone: str
    linkedin_url: str
    do_not_contact: bool
    opt_out_reason: str | None
    status: str
    merged_into_id: str | None
    crm_external_id: str | None
    is_suppressed: bool
    suppression_reason: str | None
    created_at: datetime
    updated_at: datetime


class CsvImportIn(BaseModel):
    """Bulk CSV contact import payload."""

    csv_text: str = Field(..., min_length=1, max_length=200_000)


class CsvImportOut(BaseModel):
    """Bulk CSV contact import summary."""

    accounts_created: int
    contacts_created: int
    contacts_skipped: int
    suppressed_flagged: int
    errors: list[str]


class SuppressionCreateIn(BaseModel):
    """Payload to register an email or domain suppression entry."""

    scope: Literal["email", "domain"]
    value: str = Field(..., min_length=3, max_length=255)
    reason: str = Field(..., min_length=2, max_length=255)
    source: str = Field(default="manual", max_length=64)


class SuppressionEntryOut(BaseModel):
    """Serialized suppression list entry."""

    id: str
    scope: str
    value: str
    reason: str
    source: str
    active: bool
    created_by: str
    created_at: datetime


class SuppressionApplyOut(BaseModel):
    """Result of adding or updating a suppression entry."""

    entry: SuppressionEntryOut
    contacts_affected: int
    touches_blocked: int
