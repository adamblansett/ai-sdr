import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import AuditChainVerifyOut
from app.core.auth import Actor
from app.db.base import utcnow
from app.db.models import (
    Account,
    ApprovalRequest,
    AuditEvent,
    Contact,
    DuplicateMergeCandidate,
    OutreachSequence,
    SequenceTouch,
)


def _sanitize_json_value(value: Any) -> Any:
    """Normalize values into JSON round-trip safe primitives."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _sanitize_json_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_sanitize_json_value(item) for item in value]
    return str(value)


def compute_event_hash(
    *,
    sequence_no: int,
    event_type: str,
    actor_email: str,
    actor_role: str,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any],
    prev_hash: str,
) -> str:
    """Compute a deterministic SHA-256 hash chaining an audit event to prev_hash."""
    canonical = json.dumps(
        {
            "sequence_no": sequence_no,
            "event_type": event_type,
            "actor_email": actor_email,
            "actor_role": actor_role,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "details": _sanitize_json_value(details),
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    actor: Actor,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an immutable SHA-256 hash-chained event to the audit log."""
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.desc()).limit(1)
    latest = (await db.execute(stmt)).scalar_one_or_none()

    next_seq = (latest.sequence_no + 1) if latest is not None else 1
    prev_hash = latest.event_hash if latest is not None else "GENESIS"
    clean_details = _sanitize_json_value(details or {})

    event_hash = compute_event_hash(
        sequence_no=next_seq,
        event_type=event_type,
        actor_email=actor.email,
        actor_role=actor.role,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details=clean_details,
        prev_hash=prev_hash,
    )
    event = AuditEvent(
        sequence_no=next_seq,
        event_type=event_type,
        actor_email=actor.email,
        actor_role=actor.role,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details_json=clean_details,
        prev_hash=prev_hash,
        event_hash=event_hash,
    )
    db.add(event)
    await db.flush()
    return event


async def verify_audit_chain(db: AsyncSession) -> AuditChainVerifyOut:
    """Recompute every SHA-256 link in audit_events and report integrity status."""
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.asc())
    events = list((await db.execute(stmt)).scalars().all())
    if not events:
        return AuditChainVerifyOut(
            valid=True,
            total_events=0,
            head_hash="GENESIS",
            broken_sequence_no=None,
            message="Audit trail is empty (GENESIS state verified).",
        )

    expected_prev = "GENESIS"
    expected_seq = 1
    for ev in events:
        if ev.sequence_no != expected_seq or ev.prev_hash != expected_prev:
            return AuditChainVerifyOut(
                valid=False,
                total_events=len(events),
                head_hash=events[-1].event_hash,
                broken_sequence_no=ev.sequence_no,
                message=(
                    f"Chain linkage mismatch at sequence #{ev.sequence_no}: "
                    f"expected prev_hash={expected_prev[:12]}..."
                ),
            )
        recomputed = compute_event_hash(
            sequence_no=ev.sequence_no,
            event_type=ev.event_type,
            actor_email=ev.actor_email,
            actor_role=ev.actor_role,
            entity_type=ev.entity_type,
            entity_id=ev.entity_id,
            action=ev.action,
            details=ev.details_json,
            prev_hash=ev.prev_hash,
        )
        if ev.event_hash != recomputed:
            return AuditChainVerifyOut(
                valid=False,
                total_events=len(events),
                head_hash=events[-1].event_hash,
                broken_sequence_no=ev.sequence_no,
                message=f"Hash tamper detected at sequence #{ev.sequence_no}.",
            )
        expected_prev = ev.event_hash
        expected_seq += 1

    return AuditChainVerifyOut(
        valid=True,
        total_events=len(events),
        head_hash=events[-1].event_hash,
        broken_sequence_no=None,
        message=f"All {len(events)} audit events verified intact.",
    )


async def create_approval_request(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    action_requested: str,
    summary: str,
    risk_level: str,
    requested_by: str,
) -> ApprovalRequest:
    """Create a pending human-in-the-loop approval request."""
    approval = ApprovalRequest(
        entity_type=entity_type,
        entity_id=entity_id,
        action_requested=action_requested,
        summary=summary[:400],
        risk_level=risk_level,
        status="pending",
        requested_by=requested_by,
    )
    db.add(approval)
    await db.flush()
    return approval


async def _refresh_sequence_status(db: AsyncSession, sequence: OutreachSequence) -> None:
    touches = list(
        (
            await db.execute(
                select(SequenceTouch).where(SequenceTouch.sequence_id == sequence.id)
            )
        )
        .scalars()
        .all()
    )
    statuses = {t.status for t in touches}
    if not statuses:
        return
    if "blocked_suppressed" in statuses:
        sequence.status = "blocked_suppressed"
    elif statuses == {"sent"}:
        sequence.status = "completed"
    elif "approved" in statuses or "sent" in statuses:
        sequence.status = "active"
    elif "pending_approval" in statuses:
        sequence.status = "pending_approval"
    elif statuses == {"rejected"}:
        sequence.status = "paused"


async def decide_approval(
    db: AsyncSession,
    *,
    approval_id: str,
    decision: Literal["approved", "rejected"],
    notes: str,
    actor: Actor,
) -> ApprovalRequest:
    """Approve or reject a pending HITL gate and apply domain side effects atomically."""
    from app.crm_sync.hygiene import execute_contact_merge
    from app.prospecting.service import check_contact_suppression

    approval = await db.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval request '{approval_id}' is already '{approval.status}'.",
        )

    clean_notes = notes.strip() or f"{decision} by {actor.email}"

    if approval.entity_type == "sequence_touch":
        touch = await db.get(SequenceTouch, approval.entity_id)
        if touch is None:
            touch = (
                await db.execute(
                    select(SequenceTouch).where(SequenceTouch.approval_id == approval.id)
                )
            ).scalar_one_or_none()
        if touch is not None:
            sequence = await db.get(OutreachSequence, touch.sequence_id)
            if decision == "approved" and sequence is not None:
                contact = await db.get(Contact, sequence.contact_id)
                account = await db.get(Account, sequence.account_id)
                if contact is not None:
                    suppressed, reason = await check_contact_suppression(db, contact, account)
                    if suppressed:
                        touch.status = "blocked_suppressed"
                        sequence.status = "blocked_suppressed"
                        approval.status = "rejected"
                        approval.decided_by = actor.email
                        approval.decision_notes = (
                            f"Blocked by active suppression list ({reason or 'opt-out'})"
                        )
                        approval.decided_at = utcnow()
                        await record_audit_event(
                            db,
                            event_type="sequence.approval_blocked_suppressed",
                            actor=actor,
                            entity_type="sequence_touch",
                            entity_id=touch.id,
                            action="blocked_suppressed",
                            details={
                                "approval_id": approval.id,
                                "reason": reason or "suppressed",
                            },
                        )
                        await db.commit()
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Touch blocked by active suppression list: {reason}",
                        )

            touch.status = decision
            if decision == "approved":
                touch.approved_by = actor.email
                touch.approved_at = utcnow()
            else:
                touch.approved_by = None
                touch.approved_at = None
            if sequence is not None:
                await _refresh_sequence_status(db, sequence)

    elif approval.entity_type == "crm_merge":
        candidate = await db.get(DuplicateMergeCandidate, approval.entity_id)
        if candidate is None:
            candidate = (
                await db.execute(
                    select(DuplicateMergeCandidate).where(
                        DuplicateMergeCandidate.approval_id == approval.id
                    )
                )
            ).scalar_one_or_none()
        if candidate is not None:
            if decision == "approved":
                await execute_contact_merge(db, candidate, actor)
            else:
                candidate.status = "dismissed"
                candidate.resolved_at = utcnow()

    approval.status = decision
    approval.decided_by = actor.email
    approval.decision_notes = clean_notes
    approval.decided_at = utcnow()

    await record_audit_event(
        db,
        event_type="approval.decided",
        actor=actor,
        entity_type=approval.entity_type,
        entity_id=approval.entity_id,
        action=decision,
        details={
            "approval_id": approval.id,
            "decision": decision,
            "notes": approval.decision_notes,
        },
    )
    await db.commit()
    await db.refresh(approval)
    return approval
