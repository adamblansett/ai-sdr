"""initial AI SDR schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("domain", sa.String(length=200), nullable=False),
        sa.Column("industry", sa.String(length=120), nullable=False),
        sa.Column("employee_count", sa.Integer(), nullable=False),
        sa.Column("annual_revenue_usd", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("headquarters", sa.String(length=200), nullable=False),
        sa.Column("tech_stack_json", sa.JSON(), nullable=False),
        sa.Column("icp_fit_score", sa.Integer(), nullable=False),
        sa.Column("signal_score", sa.Integer(), nullable=False),
        sa.Column("research_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain"),
    )
    op.create_index("ix_accounts_domain", "accounts", ["domain"], unique=True)
    op.create_index("ix_accounts_status", "accounts", ["status"], unique=False)

    op.create_table(
        "suppression_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "value", name="uq_suppression_scope_value"),
    )
    op.create_index(
        "ix_suppression_entries_value", "suppression_entries", ["value"], unique=False
    )

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("action_requested", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.String(length=400), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_approval_requests_entity_id", "approval_requests", ["entity_id"], unique=False
    )
    op.create_index(
        "ix_approval_requests_entity_type", "approval_requests", ["entity_type"], unique=False
    )
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sequence_no"),
    )
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"], unique=False)
    op.create_index("ix_audit_events_sequence_no", "audit_events", ["sequence_no"], unique=True)

    op.create_table(
        "crm_webhook_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_summary", sa.String(length=300), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_crm_webhook_events_event_type", "crm_webhook_events", ["event_type"], unique=False
    )
    op.create_index(
        "ix_crm_webhook_events_idempotency_key",
        "crm_webhook_events",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_crm_webhook_events_source", "crm_webhook_events", ["source"], unique=False
    )

    op.create_table(
        "account_signals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_excerpt", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_signals_account_id", "account_signals", ["account_id"], unique=False
    )
    op.create_index(
        "ix_account_signals_signal_type", "account_signals", ["signal_type"], unique=False
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("seniority", sa.String(length=32), nullable=False),
        sa.Column("department", sa.String(length=80), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("linkedin_url", sa.String(length=300), nullable=False),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False),
        sa.Column("opt_out_reason", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("merged_into_id", sa.String(length=36), nullable=True),
        sa.Column("crm_external_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_account_id", "contacts", ["account_id"], unique=False)
    op.create_index("ix_contacts_crm_external_id", "contacts", ["crm_external_id"], unique=False)
    op.create_index("ix_contacts_email", "contacts", ["email"], unique=False)
    op.create_index("ix_contacts_status", "contacts", ["status"], unique=False)

    op.create_table(
        "qualification_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("icp_score", sa.Integer(), nullable=False),
        sa.Column("intent_tier", sa.String(length=32), nullable=False),
        sa.Column("grade", sa.String(length=4), nullable=False),
        sa.Column("bant_json", sa.JSON(), nullable=False),
        sa.Column("meddic_json", sa.JSON(), nullable=False),
        sa.Column("rubric_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("evidence_citations_json", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("llm_provider", sa.String(length=32), nullable=False),
        sa.Column("llm_model", sa.String(length=120), nullable=False),
        sa.Column("pii_redacted", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qualification_records_account_id",
        "qualification_records",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_qualification_records_contact_id",
        "qualification_records",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        "ix_qualification_records_intent_tier",
        "qualification_records",
        ["intent_tier"],
        unique=False,
    )

    op.create_table(
        "outreach_sequences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("goal", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outreach_sequences_account_id", "outreach_sequences", ["account_id"], unique=False
    )
    op.create_index(
        "ix_outreach_sequences_contact_id", "outreach_sequences", ["contact_id"], unique=False
    )
    op.create_index(
        "ix_outreach_sequences_status", "outreach_sequences", ["status"], unique=False
    )

    op.create_table(
        "sequence_touches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sequence_id", sa.String(length=36), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("delay_days", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("unsubscribe_footer_included", sa.Boolean(), nullable=False),
        sa.Column("cited_signal_ids_json", sa.JSON(), nullable=False),
        sa.Column("grounded_facts_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("llm_provider", sa.String(length=32), nullable=False),
        sa.Column("llm_model", sa.String(length=120), nullable=False),
        sa.Column("pii_redacted", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sequence_id"], ["outreach_sequences.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sequence_touches_approval_id", "sequence_touches", ["approval_id"], unique=False
    )
    op.create_index(
        "ix_sequence_touches_sequence_id", "sequence_touches", ["sequence_id"], unique=False
    )
    op.create_index("ix_sequence_touches_status", "sequence_touches", ["status"], unique=False)

    op.create_table(
        "crm_deals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=True),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("primary_contact_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("amount_usd", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column("owner_email", sa.String(length=255), nullable=False),
        sa.Column("next_step", sa.Text(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hygiene_score", sa.Integer(), nullable=False),
        sa.Column("hygiene_issues_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["primary_contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_crm_deals_account_id", "crm_deals", ["account_id"], unique=False)
    op.create_index(
        "ix_crm_deals_primary_contact_id", "crm_deals", ["primary_contact_id"], unique=False
    )
    op.create_index("ix_crm_deals_stage", "crm_deals", ["stage"], unique=False)

    op.create_table(
        "duplicate_merge_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("primary_contact_id", sa.String(length=36), nullable=False),
        sa.Column("duplicate_contact_id", sa.String(length=36), nullable=False),
        sa.Column("match_reason", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["duplicate_contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["primary_contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_duplicate_merge_candidates_approval_id",
        "duplicate_merge_candidates",
        ["approval_id"],
        unique=False,
    )
    op.create_index(
        "ix_duplicate_merge_candidates_duplicate_contact_id",
        "duplicate_merge_candidates",
        ["duplicate_contact_id"],
        unique=False,
    )
    op.create_index(
        "ix_duplicate_merge_candidates_primary_contact_id",
        "duplicate_merge_candidates",
        ["primary_contact_id"],
        unique=False,
    )
    op.create_index(
        "ix_duplicate_merge_candidates_status",
        "duplicate_merge_candidates",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("duplicate_merge_candidates")
    op.drop_table("crm_deals")
    op.drop_table("sequence_touches")
    op.drop_table("outreach_sequences")
    op.drop_table("qualification_records")
    op.drop_table("contacts")
    op.drop_table("account_signals")
    op.drop_table("crm_webhook_events")
    op.drop_table("audit_events")
    op.drop_table("approval_requests")
    op.drop_table("suppression_entries")
    op.drop_table("accounts")
