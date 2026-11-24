import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import create_approval_request, record_audit_event
from app.core.auth import Actor
from app.db.base import utcnow
from app.db.models import (
    Account,
    AccountSignal,
    ApprovalRequest,
    Contact,
    CrmDeal,
    OutreachSequence,
    QualificationRecord,
    SequenceTouch,
)
from app.llm.router import LLMRouter
from app.prospecting.service import check_contact_suppression
from app.sequences.schemas import SequenceOut, SequenceTouchOut

UNSUBSCRIBE_FOOTER = (
    "To opt out of future messages, reply 'UNSUBSCRIBE' and we will immediately "
    "suppress your address."
)

_STEP_DELAYS = (0, 3, 7, 11, 16)


def touch_to_out(touch: SequenceTouch) -> SequenceTouchOut:
    """Serialize a SequenceTouch ORM row."""
    return SequenceTouchOut(
        id=touch.id,
        sequence_id=touch.sequence_id,
        step_number=touch.step_number,
        delay_days=touch.delay_days,
        channel=touch.channel,
        subject=touch.subject,
        body=touch.body,
        unsubscribe_footer_included=touch.unsubscribe_footer_included,
        cited_signal_ids=list(touch.cited_signal_ids_json or []),
        grounded_facts=list(touch.grounded_facts_json or []),
        status=touch.status,
        approval_id=touch.approval_id,
        llm_provider=touch.llm_provider,
        llm_model=touch.llm_model,
        pii_redacted=touch.pii_redacted,
        approved_by=touch.approved_by,
        approved_at=touch.approved_at,
        sent_at=touch.sent_at,
        provider_message_id=touch.provider_message_id,
        created_at=touch.created_at,
    )


def sequence_to_out(sequence: OutreachSequence, touches: list[SequenceTouch]) -> SequenceOut:
    """Serialize an OutreachSequence with ordered touches."""
    ordered = sorted(touches, key=lambda t: t.step_number)
    return SequenceOut(
        id=sequence.id,
        name=sequence.name,
        account_id=sequence.account_id,
        contact_id=sequence.contact_id,
        channel=sequence.channel,
        goal=sequence.goal,
        status=sequence.status,
        created_by=sequence.created_by,
        created_at=sequence.created_at,
        updated_at=sequence.updated_at,
        touches=[touch_to_out(t) for t in ordered],
    )


def _parse_subject_and_body(content: str, fallback_subject: str) -> tuple[str, str]:
    lines = content.strip().splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0][len("subject:") :].strip() or fallback_subject
        body = "\n".join(lines[1:]).strip()
        return subject[:300], body or content.strip()
    return fallback_subject[:300], content.strip()


def _ensure_unsubscribe_footer(body: str) -> str:
    if UNSUBSCRIBE_FOOTER.lower() in body.lower() or "unsubscribe" in body.lower():
        return body.strip()
    return f"{body.strip()}\n\n---\n{UNSUBSCRIBE_FOOTER}"


async def generate_sequence(
    db: AsyncSession,
    *,
    account_id: str,
    contact_id: str,
    name: str,
    channel: str,
    goal: str,
    num_steps: int,
    llm_router: LLMRouter,
    actor: Actor,
) -> tuple[OutreachSequence, list[SequenceTouch]]:
    """Generate a fact-grounded outbound sequence queued for human approval."""
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )

    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contact '{contact_id}' not found.",
        )
    if contact.account_id != account.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contact does not belong to the specified account.",
        )
    if contact.status == "merged":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot generate sequence for a merged duplicate contact.",
        )

    suppressed, sup_reason = await check_contact_suppression(db, contact, account)
    if suppressed:
        await record_audit_event(
            db,
            event_type="sequence.blocked_suppressed",
            actor=actor,
            entity_type="contact",
            entity_id=contact.id,
            action="blocked_suppressed",
            details={"account_id": account.id, "reason": sup_reason or "suppressed"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Outbound sequencing blocked: {sup_reason}",
        )

    signals = list(
        (
            await db.execute(
                select(AccountSignal)
                .where(AccountSignal.account_id == account.id, AccountSignal.verified.is_(True))
                .order_by(AccountSignal.weight.desc(), AccountSignal.confidence.desc())
            )
        )
        .scalars()
        .all()
    )
    latest_qual = (
        await db.execute(
            select(QualificationRecord)
            .where(QualificationRecord.account_id == account.id)
            .order_by(QualificationRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    cited_signal_ids = [s.id for s in signals[:4]]
    grounded_facts = [
        f"{s.signal_type.upper()}: {s.title} ({s.source_url or 'verified public source'})"
        for s in signals[:4]
    ]
    if not grounded_facts:
        grounded_facts = [
            f"Company profile: {account.name} ({account.industry or 'B2B'}, "
            f"{account.employee_count} employees)"
        ]
    if latest_qual is not None:
        grounded_facts.append(
            f"Qualification: Grade {latest_qual.grade} ({latest_qual.intent_tier} intent, "
            f"ICP {latest_qual.icp_score}/100)"
        )

    seq_name = name.strip() or f"{account.name} — {contact.first_name} {contact.last_name} Outbound"
    sequence = OutreachSequence(
        name=seq_name[:200],
        account_id=account.id,
        contact_id=contact.id,
        channel=channel,
        goal=goal.strip(),
        status="pending_approval",
        created_by=actor.email,
    )
    db.add(sequence)
    await db.flush()

    primary_fact = (
        signals[0].title if signals else f"{account.industry or 'B2B'} growth initiatives"
    )
    touches: list[SequenceTouch] = []
    for step_idx in range(1, num_steps + 1):
        delay_days = (
            _STEP_DELAYS[step_idx - 1] if step_idx - 1 < len(_STEP_DELAYS) else step_idx * 4
        )
        step_channel = (
            ("linkedin" if step_idx % 2 == 0 else "email")
            if channel == "multi_channel"
            else channel
        )

        # Build prompt without raw contact email/phone PII.
        prompt = (
            f"Step: {step_idx}\n"
            f"Channel: {step_channel}\n"
            f"Goal: {goal.strip()}\n"
            f"Contact Placeholder: {{{{first_name}}}}\n"
            f"Contact Title: {contact.title or contact.seniority}\n"
            f"Company Placeholder: {{{{company_name}}}}\n"
            f"Primary Fact: {primary_fact}\n"
            f"Grounded Context: {'; '.join(grounded_facts)}"
        )
        llm_res = await llm_router.generate(
            prompt=prompt,
            system_prompt=(
                "Write a concise, respectful B2B outreach step grounded only in the provided "
                "verified facts. Use {{first_name}} and {{company_name}} placeholders."
            ),
            task_type="sequence_draft",
        )
        raw_subject, raw_body = _parse_subject_and_body(
            llm_res.content,
            fallback_subject=f"{account.name}: {goal.strip()[:80]} (Step {step_idx})",
        )
        hydrated_subject = raw_subject.replace("{{first_name}}", contact.first_name).replace(
            "{{company_name}}", account.name
        )
        hydrated_body = raw_body.replace("{{first_name}}", contact.first_name).replace(
            "{{company_name}}", account.name
        )
        final_body = _ensure_unsubscribe_footer(hydrated_body)

        touch = SequenceTouch(
            sequence_id=sequence.id,
            step_number=step_idx,
            delay_days=delay_days,
            channel=step_channel,
            subject=hydrated_subject[:300],
            body=final_body,
            unsubscribe_footer_included=True,
            cited_signal_ids_json=cited_signal_ids,
            grounded_facts_json=grounded_facts,
            status="pending_approval",
            llm_provider=llm_res.provider,
            llm_model=llm_res.model,
            pii_redacted=llm_res.pii_redacted,
        )
        db.add(touch)
        await db.flush()

        approval = await create_approval_request(
            db,
            entity_type="sequence_touch",
            entity_id=touch.id,
            action_requested="send_outbound_touch",
            summary=(
                f"Step {step_idx} ({step_channel}) to {contact.first_name} {contact.last_name} "
                f"at {account.name}: {hydrated_subject[:120]}"
            ),
            risk_level="medium" if step_idx == 1 else "low",
            requested_by=actor.email,
        )
        touch.approval_id = approval.id
        touches.append(touch)

    await record_audit_event(
        db,
        event_type="sequence.generated",
        actor=actor,
        entity_type="outreach_sequence",
        entity_id=sequence.id,
        action="generated",
        details={
            "account_id": account.id,
            "contact_id": contact.id,
            "num_steps": num_steps,
            "cited_signals": len(cited_signal_ids),
        },
    )
    await db.commit()
    await db.refresh(sequence)
    for t in touches:
        await db.refresh(t)
    return sequence, touches


async def update_touch_draft(
    db: AsyncSession,
    *,
    touch_id: str,
    subject: str | None,
    body: str | None,
    actor: Actor,
) -> SequenceTouch:
    """Edit an outbound touch draft; editing an approved/rejected touch requires re-approval."""
    touch = await db.get(SequenceTouch, touch_id)
    if touch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sequence touch '{touch_id}' not found.",
        )
    if touch.status in ("sent", "blocked_suppressed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot edit touch in '{touch.status}' state.",
        )

    if subject is not None:
        touch.subject = subject.strip()[:300]
    if body is not None:
        touch.body = _ensure_unsubscribe_footer(body)
        touch.unsubscribe_footer_included = True

    sequence = await db.get(OutreachSequence, touch.sequence_id)
    requires_reapproval = touch.status in ("approved", "rejected")
    if requires_reapproval:
        touch.status = "pending_approval"
        touch.approved_by = None
        touch.approved_at = None
        new_approval = await create_approval_request(
            db,
            entity_type="sequence_touch",
            entity_id=touch.id,
            action_requested="send_outbound_touch",
            summary=(
                f"Re-approval after draft edit (Step {touch.step_number}): "
                f"{touch.subject[:120]}"
            ),
            risk_level="medium",
            requested_by=actor.email,
        )
        touch.approval_id = new_approval.id
        if sequence is not None:
            sequence.status = "pending_approval"
        event_type = "sequence.touch_edited_reapproval_required"
    else:
        if touch.approval_id:
            existing_app = await db.get(ApprovalRequest, touch.approval_id)
            if existing_app is not None and existing_app.status == "pending":
                existing_app.summary = f"Step {touch.step_number} draft: {touch.subject[:160]}"
        event_type = "sequence.touch_edited"

    await record_audit_event(
        db,
        event_type=event_type,
        actor=actor,
        entity_type="sequence_touch",
        entity_id=touch.id,
        action="edited",
        details={
            "requires_reapproval": requires_reapproval,
            "approval_id": touch.approval_id,
        },
    )
    await db.commit()
    await db.refresh(touch)
    return touch


async def send_approved_touch(
    db: AsyncSession,
    *,
    touch_id: str,
    actor: Actor,
) -> SequenceTouch:
    """Dispatch an approved outbound touch after re-validating suppression and footer."""
    touch = await db.get(SequenceTouch, touch_id)
    if touch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sequence touch '{touch_id}' not found.",
        )

    if touch.status == "sent":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Touch was already sent.",
        )
    if touch.status == "blocked_suppressed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Touch is blocked by active suppression list.",
        )
    if touch.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Human approval is required before sending outbound touches.",
        )

    if not touch.unsubscribe_footer_included or "unsubscribe" not in touch.body.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Outbound touch must include an unsubscribe opt-out footer.",
        )

    sequence = await db.get(OutreachSequence, touch.sequence_id)
    if sequence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Parent sequence '{touch.sequence_id}' not found.",
        )

    contact = await db.get(Contact, sequence.contact_id)
    account = await db.get(Account, sequence.account_id)
    if contact is not None:
        suppressed, sup_reason = await check_contact_suppression(db, contact, account)
        if suppressed:
            touch.status = "blocked_suppressed"
            sequence.status = "blocked_suppressed"
            await record_audit_event(
                db,
                event_type="sequence.send_blocked_suppressed",
                actor=actor,
                entity_type="sequence_touch",
                entity_id=touch.id,
                action="blocked_suppressed",
                details={"reason": sup_reason or "suppressed"},
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Send blocked by active suppression list: {sup_reason}",
            )

    touch.status = "sent"
    touch.sent_at = utcnow()
    touch.provider_message_id = f"msg-{uuid.uuid4().hex[:12]}"

    all_touches = list(
        (
            await db.execute(
                select(SequenceTouch).where(SequenceTouch.sequence_id == sequence.id)
            )
        )
        .scalars()
        .all()
    )
    if all(t.status == "sent" for t in all_touches):
        sequence.status = "completed"
    else:
        sequence.status = "active"

    open_deals = list(
        (
            await db.execute(
                select(CrmDeal).where(
                    CrmDeal.account_id == sequence.account_id,
                    CrmDeal.stage.notin_(["closed_won", "closed_lost"]),
                )
            )
        )
        .scalars()
        .all()
    )
    for deal in open_deals:
        deal.last_activity_at = touch.sent_at

    await record_audit_event(
        db,
        event_type="sequence.touch_sent",
        actor=actor,
        entity_type="sequence_touch",
        entity_id=touch.id,
        action="sent",
        details={
            "sequence_id": sequence.id,
            "step_number": touch.step_number,
            "provider_message_id": touch.provider_message_id,
        },
    )
    await db.commit()
    await db.refresh(touch)
    return touch
