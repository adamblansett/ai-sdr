import re
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import create_approval_request, record_audit_event
from app.core.auth import Actor
from app.crm_sync.schemas import (
    CrmDealCreateIn,
    CrmDealOut,
    DuplicateMergeCandidateOut,
    HygieneIssueOut,
    HygieneValidateOut,
)
from app.db.base import as_utc, quantize_money, utcnow
from app.db.models import (
    Account,
    AccountSignal,
    Contact,
    CrmDeal,
    DuplicateMergeCandidate,
    OutreachSequence,
    QualificationRecord,
    SequenceTouch,
)
from app.llm.router import LLMRouter
from app.prospecting.suppression import (
    check_contact_suppression,
    extract_email_domain,
    normalize_email,
)


def deal_to_out(deal: CrmDeal) -> CrmDealOut:
    """Serialize a CrmDeal ORM row."""
    return CrmDealOut(
        id=deal.id,
        external_id=deal.external_id,
        account_id=deal.account_id,
        primary_contact_id=deal.primary_contact_id,
        name=deal.name,
        stage=deal.stage,
        amount_usd=float(deal.amount_usd),
        close_date=deal.close_date,
        owner_email=deal.owner_email,
        next_step=deal.next_step,
        last_activity_at=deal.last_activity_at,
        hygiene_score=deal.hygiene_score,
        hygiene_issues=[HygieneIssueOut(**item) for item in (deal.hygiene_issues_json or [])],
        created_at=deal.created_at,
        updated_at=deal.updated_at,
    )


async def candidate_to_out(
    db: AsyncSession, candidate: DuplicateMergeCandidate
) -> DuplicateMergeCandidateOut:
    """Serialize DuplicateMergeCandidate enriched with contact names and emails."""
    primary = await db.get(Contact, candidate.primary_contact_id)
    duplicate = await db.get(Contact, candidate.duplicate_contact_id)
    return DuplicateMergeCandidateOut(
        id=candidate.id,
        primary_contact_id=candidate.primary_contact_id,
        duplicate_contact_id=candidate.duplicate_contact_id,
        primary_email=primary.email if primary else "",
        duplicate_email=duplicate.email if duplicate else "",
        primary_name=f"{primary.first_name} {primary.last_name}".strip() if primary else "",
        duplicate_name=f"{duplicate.first_name} {duplicate.last_name}".strip() if duplicate else "",
        match_reason=candidate.match_reason,
        confidence=candidate.confidence,
        status=candidate.status,
        approval_id=candidate.approval_id,
        created_at=candidate.created_at,
        resolved_at=candidate.resolved_at,
    )


async def validate_deal_hygiene(
    db: AsyncSession,
    deal: CrmDeal,
) -> tuple[int, list[dict[str, str]]]:
    """Evaluate CRM stage hygiene, stale activity, close dates, and qualification alignment."""
    if deal.stage in ("closed_won", "closed_lost"):
        deal.hygiene_score = 100
        deal.hygiene_issues_json = []
        return 100, []

    issues: list[dict[str, str]] = []
    penalty = 0

    if deal.close_date is None:
        penalty += 15
        issues.append(
            {
                "code": "missing_close_date",
                "severity": "medium",
                "message": "Open deal is missing a target close date.",
            }
        )
    elif deal.close_date < date.today():
        penalty += 20
        issues.append(
            {
                "code": "past_close_date",
                "severity": "high",
                "message": f"Target close date ({deal.close_date.isoformat()}) is in the past.",
            }
        )

    stale_days = (utcnow() - as_utc(deal.last_activity_at)).days
    if stale_days > 14:
        penalty += 20
        issues.append(
            {
                "code": "stale_activity",
                "severity": "high",
                "message": f"No recorded activity in {stale_days} days (>14d SLA).",
            }
        )

    if not deal.next_step.strip():
        penalty += 15
        issues.append(
            {
                "code": "missing_next_step",
                "severity": "medium",
                "message": "Deal is missing a concrete next step.",
            }
        )

    if not deal.primary_contact_id:
        penalty += 15
        issues.append(
            {
                "code": "missing_primary_contact",
                "severity": "medium",
                "message": "Open deal has no primary contact assigned.",
            }
        )
    else:
        primary_contact = await db.get(Contact, deal.primary_contact_id)
        if primary_contact is not None:
            suppressed, sup_reason = await check_contact_suppression(db, primary_contact)
            if suppressed:
                penalty += 25
                issues.append(
                    {
                        "code": "suppressed_primary_contact",
                        "severity": "high",
                        "message": f"Primary contact is suppressed ({sup_reason}).",
                    }
                )

    if deal.stage in ("qualification", "proposal", "negotiation") and deal.amount_usd <= 0:
        penalty += 15
        issues.append(
            {
                "code": "missing_amount",
                "severity": "medium",
                "message": "Qualified/late-stage deal requires a positive amount_usd.",
            }
        )

    if deal.stage in ("proposal", "negotiation"):
        qual = (
            await db.execute(
                select(QualificationRecord).where(
                    QualificationRecord.account_id == deal.account_id,
                    QualificationRecord.intent_tier != "disqualified",
                )
            )
        ).scalars().first()
        if qual is None:
            penalty += 20
            issues.append(
                {
                    "code": "missing_qualification",
                    "severity": "high",
                    "message": (
                        "Proposal/negotiation stage requires an active qualification record."
                    ),
                }
            )

    score = max(0, 100 - penalty)
    deal.hygiene_score = score
    deal.hygiene_issues_json = issues
    return score, issues


async def create_deal(
    db: AsyncSession,
    *,
    payload: CrmDealCreateIn,
    actor: Actor,
) -> CrmDeal:
    """Create a CRM pipeline deal and evaluate initial hygiene."""
    account = await db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{payload.account_id}' not found.",
        )

    if payload.primary_contact_id:
        contact = await db.get(Contact, payload.primary_contact_id)
        if contact is None or contact.account_id != account.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Primary contact does not exist on the target account.",
            )

    if payload.external_id:
        ext_val = payload.external_id.strip()
        dup = (
            await db.execute(select(CrmDeal).where(CrmDeal.external_id == ext_val))
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Deal with external_id '{payload.external_id}' already exists.",
            )

    deal = CrmDeal(
        external_id=payload.external_id.strip() if payload.external_id else None,
        account_id=account.id,
        primary_contact_id=payload.primary_contact_id,
        name=payload.name.strip(),
        stage=payload.stage,
        amount_usd=quantize_money(payload.amount_usd),
        close_date=payload.close_date,
        owner_email=payload.owner_email.strip() or actor.email,
        next_step=payload.next_step.strip(),
        last_activity_at=payload.last_activity_at or utcnow(),
    )
    await validate_deal_hygiene(db, deal)
    db.add(deal)
    await db.flush()

    await record_audit_event(
        db,
        event_type="crm.deal_created",
        actor=actor,
        entity_type="crm_deal",
        entity_id=deal.id,
        action="created",
        details={
            "account_id": account.id,
            "stage": deal.stage,
            "hygiene_score": deal.hygiene_score,
        },
    )
    await db.commit()
    await db.refresh(deal)
    return deal


async def validate_all_deals(
    db: AsyncSession, *, actor: Actor, commit: bool = True
) -> HygieneValidateOut:
    """Re-run hygiene validation across every CRM deal in the pipeline."""
    stmt = select(CrmDeal).order_by(CrmDeal.created_at.desc())
    deals = list((await db.execute(stmt)).scalars().all())
    flagged = 0
    scores: list[int] = []
    for deal in deals:
        score, issues = await validate_deal_hygiene(db, deal)
        scores.append(score)
        if issues:
            flagged += 1

    avg_score = round(sum(scores) / len(scores), 1) if scores else 100.0
    await record_audit_event(
        db,
        event_type="crm.hygiene_validated",
        actor=actor,
        entity_type="crm_pipeline",
        entity_id="all-deals",
        action="validated",
        details={
            "deals_checked": len(deals),
            "deals_flagged": flagged,
            "avg_hygiene_score": avg_score,
        },
    )
    if commit:
        await db.commit()
        for deal in deals:
            await db.refresh(deal)
    return HygieneValidateOut(
        deals_checked=len(deals),
        deals_flagged=flagged,
        avg_hygiene_score=avg_score,
        deals=[deal_to_out(d) for d in deals],
    )


async def synthesize_deal_next_step(
    db: AsyncSession,
    *,
    deal_id: str,
    llm_router: LLMRouter,
    actor: Actor,
) -> CrmDeal:
    """Generate an actionable CRM next step from account signals, qualification, and touches."""
    deal = await db.get(CrmDeal, deal_id)
    if deal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CRM deal '{deal_id}' not found.",
        )

    account = await db.get(Account, deal.account_id)
    signals = list(
        (
            await db.execute(
                select(AccountSignal)
                .where(
                    AccountSignal.account_id == deal.account_id,
                    AccountSignal.verified.is_(True),
                )
                .order_by(AccountSignal.observed_at.desc())
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    qual = (
        await db.execute(
            select(QualificationRecord)
            .where(QualificationRecord.account_id == deal.account_id)
            .order_by(QualificationRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    seq_ids = list(
        (
            await db.execute(
                select(OutreachSequence.id).where(OutreachSequence.account_id == deal.account_id)
            )
        )
        .scalars()
        .all()
    )
    sent_count = 0
    if seq_ids:
        sent_touches = list(
            (
                await db.execute(
                    select(SequenceTouch).where(
                        SequenceTouch.sequence_id.in_(seq_ids),
                        SequenceTouch.status == "sent",
                    )
                )
            )
            .scalars()
            .all()
        )
        sent_count = len(sent_touches)

    context_parts = [
        f"Account {account.name if account else deal.account_id}",
        f"{len(signals)} verified signals",
        f"{sent_count} outbound touches sent",
    ]
    if qual is not None:
        context_parts.append(f"Qualification Grade {qual.grade} ({qual.intent_tier} intent)")
    if deal.hygiene_issues_json:
        issue_codes = ", ".join(str(item.get("code", "")) for item in deal.hygiene_issues_json)
        context_parts.append(f"Resolve hygiene items: {issue_codes}")

    prompt = (
        f"Deal: {deal.name}\n"
        f"Stage: {deal.stage}\n"
        f"Amount USD: {float(deal.amount_usd):.2f}\n"
        f"Context: {'; '.join(context_parts)}"
    )
    llm_res = await llm_router.generate(
        prompt=prompt,
        system_prompt="Produce a single clear, concrete CRM next step for the account executive.",
        task_type="crm_next_step",
    )
    deal.next_step = llm_res.content
    await validate_deal_hygiene(db, deal)

    await record_audit_event(
        db,
        event_type="crm.next_step_synthesized",
        actor=actor,
        entity_type="crm_deal",
        entity_id=deal.id,
        action="updated",
        details={
            "llm_provider": llm_res.provider,
            "hygiene_score": deal.hygiene_score,
        },
    )
    await db.commit()
    await db.refresh(deal)
    return deal


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone)


async def scan_duplicate_contacts(
    db: AsyncSession,
    *,
    actor: Actor,
) -> list[DuplicateMergeCandidate]:
    """Detect duplicate active contacts and queue HITL merge approvals."""
    contacts = list(
        (
            await db.execute(
                select(Contact)
                .where(Contact.status != "merged")
                .order_by(Contact.created_at.asc(), Contact.id.asc())
            )
        )
        .scalars()
        .all()
    )
    existing_candidates = list((await db.execute(select(DuplicateMergeCandidate))).scalars().all())
    seen_pairs: set[frozenset[str]] = {
        frozenset({c.primary_contact_id, c.duplicate_contact_id})
        for c in existing_candidates
        if c.status in ("pending_approval", "merged")
    }
    claimed_duplicates: set[str] = {
        c.duplicate_contact_id for c in existing_candidates if c.status == "pending_approval"
    }

    created: list[DuplicateMergeCandidate] = []
    for idx, left in enumerate(contacts):
        if left.id in claimed_duplicates:
            continue
        for right in contacts[idx + 1 :]:
            if right.id in claimed_duplicates:
                continue
            pair = frozenset({left.id, right.id})
            if pair in seen_pairs:
                continue

            match_reason: str | None = None
            confidence = 0.0
            left_email = normalize_email(left.email)
            right_email = normalize_email(right.email)
            if left_email and left_email == right_email:
                match_reason = "exact_email"
                confidence = 0.99
            else:
                left_name = (left.first_name.strip().lower(), left.last_name.strip().lower())
                right_name = (right.first_name.strip().lower(), right.last_name.strip().lower())
                left_dom = extract_email_domain(left_email)
                right_dom = extract_email_domain(right_email)
                same_org = left.account_id == right.account_id or (
                    bool(left_dom) and left_dom == right_dom
                )
                if left_name[0] and left_name[1] and left_name == right_name and same_org:
                    match_reason = "name_and_domain"
                    confidence = 0.91
                else:
                    left_digits = _digits_only(left.phone)
                    right_digits = _digits_only(right.phone)
                    if len(left_digits) >= 10 and left_digits == right_digits:
                        match_reason = "normalized_phone"
                        confidence = 0.85

            if match_reason is None:
                continue

            primary, duplicate = left, right
            if duplicate.crm_external_id and not primary.crm_external_id:
                primary, duplicate = duplicate, primary

            candidate = DuplicateMergeCandidate(
                primary_contact_id=primary.id,
                duplicate_contact_id=duplicate.id,
                match_reason=match_reason,
                confidence=confidence,
                status="pending_approval",
            )
            db.add(candidate)
            await db.flush()

            approval = await create_approval_request(
                db,
                entity_type="crm_merge",
                entity_id=candidate.id,
                action_requested="merge_duplicate_contacts",
                summary=(
                    f"Merge duplicate contact '{duplicate.first_name} {duplicate.last_name}' "
                    f"({duplicate.email}) into '{primary.first_name} {primary.last_name}' "
                    f"({primary.email}) [{match_reason}]"
                ),
                risk_level="high",
                requested_by=actor.email,
            )
            candidate.approval_id = approval.id

            await record_audit_event(
                db,
                event_type="crm.duplicate_detected",
                actor=actor,
                entity_type="duplicate_merge_candidate",
                entity_id=candidate.id,
                action="flagged",
                details={
                    "primary_contact_id": primary.id,
                    "duplicate_contact_id": duplicate.id,
                    "match_reason": match_reason,
                    "confidence": confidence,
                },
            )
            seen_pairs.add(pair)
            claimed_duplicates.add(duplicate.id)
            created.append(candidate)

    await db.commit()
    for c in created:
        await db.refresh(c)
    return created


async def execute_contact_merge(
    db: AsyncSession,
    candidate: DuplicateMergeCandidate,
    actor: Actor,
) -> None:
    """Atomically merge duplicate contact into primary while preserving opt-out flags."""
    primary = await db.get(Contact, candidate.primary_contact_id)
    duplicate = await db.get(Contact, candidate.duplicate_contact_id)
    if primary is None or duplicate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both contacts in merge candidate no longer exist.",
        )

    if not primary.title and duplicate.title:
        primary.title = duplicate.title
        primary.seniority = duplicate.seniority
    if not primary.department and duplicate.department:
        primary.department = duplicate.department
    if not primary.phone and duplicate.phone:
        primary.phone = duplicate.phone
    if not primary.linkedin_url and duplicate.linkedin_url:
        primary.linkedin_url = duplicate.linkedin_url
    if not primary.crm_external_id and duplicate.crm_external_id:
        primary.crm_external_id = duplicate.crm_external_id

    if duplicate.do_not_contact or duplicate.status == "suppressed":
        primary.do_not_contact = True
        primary.status = "suppressed"
        primary.opt_out_reason = (
            primary.opt_out_reason
            or duplicate.opt_out_reason
            or "Preserved opt-out status during duplicate contact merge"
        )

    quals = list(
        (
            await db.execute(
                select(QualificationRecord).where(QualificationRecord.contact_id == duplicate.id)
            )
        )
        .scalars()
        .all()
    )
    for q in quals:
        q.contact_id = primary.id

    sequences = list(
        (
            await db.execute(
                select(OutreachSequence).where(OutreachSequence.contact_id == duplicate.id)
            )
        )
        .scalars()
        .all()
    )
    for seq in sequences:
        seq.contact_id = primary.id

    deals = list(
        (
            await db.execute(
                select(CrmDeal).where(CrmDeal.primary_contact_id == duplicate.id)
            )
        )
        .scalars()
        .all()
    )
    for deal in deals:
        deal.primary_contact_id = primary.id
        await validate_deal_hygiene(db, deal)

    duplicate.status = "merged"
    duplicate.merged_into_id = primary.id
    candidate.status = "merged"
    candidate.resolved_at = utcnow()

    await record_audit_event(
        db,
        event_type="crm.contacts_merged",
        actor=actor,
        entity_type="contact",
        entity_id=primary.id,
        action="merged",
        details={
            "candidate_id": candidate.id,
            "duplicate_contact_id": duplicate.id,
            "relinked_qualifications": len(quals),
            "relinked_sequences": len(sequences),
            "relinked_deals": len(deals),
            "preserved_opt_out": primary.do_not_contact,
        },
    )
