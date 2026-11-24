from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor
from app.db.models import (
    Account,
    AccountSignal,
    ApprovalRequest,
    AuditEvent,
    Contact,
    CrmDeal,
    DuplicateMergeCandidate,
    OutreachSequence,
    QualificationRecord,
    SequenceTouch,
    SuppressionEntry,
)
from app.db.session import get_db

router = APIRouter(prefix="/overview", tags=["overview"])


class OverviewSummaryOut(BaseModel):
    """Aggregate KPI summary across prospecting, qualification, sequences, and CRM hygiene."""

    accounts_total: int
    suppressed_accounts: int
    signals_total: int
    contacts_active: int
    contacts_suppressed: int
    active_suppressions: int
    qualifications_total: int
    high_intent_leads: int
    avg_icp_score: float
    sequences_total: int
    touches_pending_approval: int
    touches_approved: int
    touches_sent: int
    touches_blocked: int
    deals_open: int
    avg_hygiene_score: float
    hygiene_issues_open: int
    pending_merges: int
    pending_approvals: int
    audit_events_total: int


@router.get("", response_model=OverviewSummaryOut)
async def get_overview(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> OverviewSummaryOut:
    """Return aggregate operational KPIs for the AI SDR workspace."""
    _ = actor
    accounts = list((await db.execute(select(Account))).scalars().all())
    signals = list((await db.execute(select(AccountSignal))).scalars().all())
    contacts = list((await db.execute(select(Contact))).scalars().all())
    suppressions = list((await db.execute(select(SuppressionEntry))).scalars().all())
    quals = list((await db.execute(select(QualificationRecord))).scalars().all())
    sequences = list((await db.execute(select(OutreachSequence))).scalars().all())
    touches = list((await db.execute(select(SequenceTouch))).scalars().all())
    deals = list((await db.execute(select(CrmDeal))).scalars().all())
    merges = list((await db.execute(select(DuplicateMergeCandidate))).scalars().all())
    approvals = list((await db.execute(select(ApprovalRequest))).scalars().all())
    audit_events = list((await db.execute(select(AuditEvent))).scalars().all())

    active_accounts = [a for a in accounts if a.status == "active"]
    avg_icp = (
        round(sum(a.icp_fit_score for a in active_accounts) / len(active_accounts), 1)
        if active_accounts
        else 0.0
    )
    open_deals = [d for d in deals if d.stage not in ("closed_won", "closed_lost")]
    avg_hygiene = (
        round(sum(d.hygiene_score for d in open_deals) / len(open_deals), 1)
        if open_deals
        else 100.0
    )

    return OverviewSummaryOut(
        accounts_total=len(accounts),
        suppressed_accounts=sum(1 for a in accounts if a.status == "suppressed"),
        signals_total=len(signals),
        contacts_active=sum(1 for c in contacts if c.status == "active" and not c.do_not_contact),
        contacts_suppressed=sum(
            1
            for c in contacts
            if (c.status == "suppressed" or c.do_not_contact) and c.status != "merged"
        ),
        active_suppressions=sum(1 for s in suppressions if s.active),
        qualifications_total=len(quals),
        high_intent_leads=sum(1 for q in quals if q.intent_tier == "high"),
        avg_icp_score=avg_icp,
        sequences_total=len(sequences),
        touches_pending_approval=sum(1 for t in touches if t.status == "pending_approval"),
        touches_approved=sum(1 for t in touches if t.status == "approved"),
        touches_sent=sum(1 for t in touches if t.status == "sent"),
        touches_blocked=sum(1 for t in touches if t.status == "blocked_suppressed"),
        deals_open=len(open_deals),
        avg_hygiene_score=avg_hygiene,
        hygiene_issues_open=sum(len(d.hygiene_issues_json or []) for d in open_deals),
        pending_merges=sum(1 for m in merges if m.status == "pending_approval"),
        pending_approvals=sum(1 for a in approvals if a.status == "pending"),
        audit_events_total=len(audit_events),
    )
