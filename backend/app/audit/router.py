from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import (
    ApprovalDecisionIn,
    ApprovalRequestOut,
    AuditChainVerifyOut,
    AuditEventOut,
    PiiPreviewIn,
)
from app.audit.service import decide_approval, verify_audit_chain
from app.core.auth import Actor, get_current_actor, require_roles
from app.db.models import ApprovalRequest, AuditEvent
from app.db.session import get_db
from app.llm.pii import RedactionResult, redact_pii

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/approvals", response_model=list[ApprovalRequestOut])
async def list_approvals(
    status: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRequest]:
    """List human-in-the-loop approval requests."""
    _ = actor
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    if status:
        stmt = stmt.where(ApprovalRequest.status == status.strip().lower())
    if entity_type:
        stmt = stmt.where(ApprovalRequest.entity_type == entity_type.strip().lower())
    return list((await db.execute(stmt)).scalars().all())


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalRequestOut)
async def decide_approval_endpoint(
    approval_id: str,
    body: ApprovalDecisionIn,
    actor: Actor = Depends(require_roles("sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequest:
    """Approve or reject a pending HITL request (sales_manager/admin only)."""
    return await decide_approval(
        db,
        approval_id=approval_id,
        decision=body.decision,
        notes=body.notes,
        actor=actor,
    )


@router.get("/events", response_model=list[AuditEventOut])
async def list_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[AuditEvent]:
    """List immutable audit trail events ordered newest first."""
    _ = actor
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/verify", response_model=AuditChainVerifyOut)
async def verify_audit_chain_endpoint(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> AuditChainVerifyOut:
    """Verify SHA-256 linkage across the entire audit trail."""
    _ = actor
    return await verify_audit_chain(db)


@router.post("/pii-preview", response_model=RedactionResult)
async def preview_pii_redaction(
    body: PiiPreviewIn,
    actor: Actor = Depends(get_current_actor),
) -> RedactionResult:
    """Preview outbound cloud LLM PII scrubbing without storing inputs."""
    _ = actor
    return redact_pii(body.text)
