"""phase 2 schema: auth users, replies, knowledge chunks, outbound CRM sync, workers

Revision ID: 0002_phase2_schema
Revises: 0001_initial_schema
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase2_schema"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sequence_touches") as batch_op:
        batch_op.add_column(sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("delivery_provider", sa.String(length=32), nullable=True)
        )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "inbound_replies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sequence_id", sa.String(length=36), nullable=True),
        sa.Column("touch_id", sa.String(length=36), nullable=True),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("sender_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("auto_action_taken", sa.String(length=240), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sequence_id"], ["outreach_sequences.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["touch_id"], ["sequence_touches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inbound_replies_classification", "inbound_replies", ["classification"], unique=False
    )
    op.create_index(
        "ix_inbound_replies_contact_id", "inbound_replies", ["contact_id"], unique=False
    )
    op.create_index(
        "ix_inbound_replies_sender_email", "inbound_replies", ["sender_email"], unique=False
    )
    op.create_index(
        "ix_inbound_replies_sequence_id", "inbound_replies", ["sequence_id"], unique=False
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_ref_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_chunks_account_id", "knowledge_chunks", ["account_id"], unique=False
    )
    op.create_index(
        "ix_knowledge_chunks_source_type", "knowledge_chunks", ["source_type"], unique=False
    )

    op.create_table(
        "crm_sync_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_record_id", sa.String(length=120), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("response_summary", sa.String(length=300), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_crm_sync_jobs_idempotency_key", "crm_sync_jobs", ["idempotency_key"], unique=True
    )
    op.create_index("ix_crm_sync_jobs_status", "crm_sync_jobs", ["status"], unique=False)

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("celery_task_id", sa.String(length=120), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_background_jobs_job_type", "background_jobs", ["job_type"], unique=False
    )
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("background_jobs")
    op.drop_table("crm_sync_jobs")
    op.drop_table("knowledge_chunks")
    op.drop_table("inbound_replies")
    op.drop_table("users")
    with op.batch_alter_table("sequence_touches") as batch_op:
        batch_op.drop_column("delivery_provider")
        batch_op.drop_column("scheduled_for")
