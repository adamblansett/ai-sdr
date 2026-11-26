from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_uuid, utcnow


class Account(Base):
    """Target B2B account enriched with public signals and ICP score."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    industry: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    employee_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    annual_revenue_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    headquarters: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    tech_stack_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    icp_fit_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    signal_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    research_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class AccountSignal(Base):
    """Verified public buying signal tied to an account."""

    __tablename__ = "account_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Contact(Base):
    """Prospect contact associated with a target account."""

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    seniority: Mapped[str] = mapped_column(String(32), default="manager", nullable=False)
    department: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    linkedin_url: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opt_out_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True, nullable=False)
    merged_into_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    crm_external_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class SuppressionEntry(Base):
    """Email or domain suppression / opt-out entry enforced across all outbound workflows."""

    __tablename__ = "suppression_entries"
    __table_args__ = (UniqueConstraint("scope", "value", name="uq_suppression_scope_value"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class QualificationRecord(Base):
    """Rubric-driven ICP, buying intent, and BANT/MEDDIC qualification assessment."""

    __tablename__ = "qualification_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    contact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("contacts.id", ondelete="SET NULL"), index=True, nullable=True
    )
    icp_score: Mapped[int] = mapped_column(Integer, nullable=False)
    intent_tier: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    grade: Mapped[str] = mapped_column(String(4), nullable=False)
    bant_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    meddic_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    rubric_breakdown_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    evidence_citations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    llm_model: Mapped[str] = mapped_column(
        String(120), default="deterministic-sdr-v1", nullable=False
    )
    pii_redacted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class OutreachSequence(Base):
    """Multi-touch outbound sequence anchored to a prospect contact and account."""

    __tablename__ = "outreach_sequences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    contact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contacts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), default="email", nullable=False)
    goal: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending_approval", index=True, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class SequenceTouch(Base):
    """Individual personalized touch within a sequence, gated by human approval."""

    __tablename__ = "sequence_touches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sequence_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("outreach_sequences.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="email", nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    unsubscribe_footer_included: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    cited_signal_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    grounded_facts_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending_approval", index=True, nullable=False
    )
    approval_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    llm_provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    llm_model: Mapped[str] = mapped_column(
        String(120), default="deterministic-sdr-v1", nullable=False
    )
    pii_redacted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CrmDeal(Base):
    """CRM pipeline deal monitored for stage hygiene, stale activity, and next steps."""

    __tablename__ = "crm_deals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    external_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    primary_contact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("contacts.id", ondelete="SET NULL"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="discovery", index=True, nullable=False)
    amount_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False)
    next_step: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    hygiene_score: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    hygiene_issues_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class DuplicateMergeCandidate(Base):
    """Detected duplicate contact pair queued for human merge approval."""

    __tablename__ = "duplicate_merge_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    primary_contact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contacts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    duplicate_contact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contacts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    match_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending_approval", index=True, nullable=False
    )
    approval_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CrmWebhookEvent(Base):
    """Idempotent CRM webhook log deduplicated by idempotency_key."""

    __tablename__ = "crm_webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    idempotency_key: Mapped[str] = mapped_column(
        String(160), unique=True, index=True, nullable=False
    )
    source: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="processed", nullable=False)
    result_summary: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ApprovalRequest(Base):
    """Human-in-the-loop review gate for outbound touches and CRM merges."""

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    action_requested: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(String(400), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Immutable, SHA-256 hash-chained audit trail event."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sequence_no: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class User(Base):
    """Persisted workspace user for scrypt-hashed password authentication and RBAC."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="sdr", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class InboundReply(Base):
    """Classified prospect reply tied to outbound sequences and suppression automation."""

    __tablename__ = "inbound_replies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    sequence_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("outreach_sequences.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    touch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sequence_touches.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("contacts.id", ondelete="SET NULL"), index=True, nullable=True
    )
    sender_email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    classification: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    auto_action_taken: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class KnowledgeChunk(Base):
    """Indexed account signal, case study, or playbook snippet with dense embedding."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source_ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    embedding_json: Mapped[list[float]] = mapped_column(JSON, default=list, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, default=384, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CrmSyncJob(Base):
    """Idempotent outbound CRM sync record to HubSpot, Salesforce, or mock connector."""

    __tablename__ = "crm_sync_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(160), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    external_record_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    response_summary: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackgroundJob(Base):
    """Tracked background worker execution (inline or Celery-dispatched)."""

    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
