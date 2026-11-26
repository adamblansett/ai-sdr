from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.db.base import utcnow
from app.db.models import (
    Account,
    AccountSignal,
    ApprovalRequest,
    Contact,
    OutreachSequence,
    SequenceTouch,
    SuppressionEntry,
)
from app.prospecting.schemas import SuppressionEntryOut

_TARGET_INDUSTRIES = {
    "saas",
    "cloud",
    "cloud infrastructure",
    "fintech",
    "devops",
    "healthtech",
    "logistics",
    "enterprise tech",
    "enterprise software",
    "b2b software",
    "cybersecurity",
}

_TARGET_STACK = {
    "salesforce",
    "hubspot",
    "snowflake",
    "aws",
    "kubernetes",
    "slack",
    "databricks",
    "okta",
    "gong",
    "outreach",
    "postgres",
}


def normalize_domain(domain: str) -> str:
    """Normalize a domain string by stripping scheme, www prefix, port, and path."""
    raw = domain.strip().lower()
    if "://" in raw:
        parsed = urlparse(raw)
        raw = parsed.netloc or parsed.path
    raw = raw.split("/")[0].split("?")[0].split(":")[0].strip()
    if raw.startswith("www."):
        raw = raw[4:]
    return raw


def normalize_email(email: str) -> str:
    """Normalize an email address to trimmed lowercase."""
    return email.strip().lower()


def extract_email_domain(email: str) -> str:
    """Extract normalized domain from an email address."""
    norm = normalize_email(email)
    if "@" not in norm:
        return ""
    return normalize_domain(norm.split("@", 1)[1])


def infer_seniority(title: str) -> str:
    """Infer standardized buyer seniority tier from job title."""
    t = title.strip().lower()
    if any(k in t for k in ("chief ", "ceo", "cfo", "cro", "cto", "coo", "ciso", "cmo", "founder")):
        return "c_level"
    if "vp" in t or "vice president" in t or "svp" in t or "evp" in t:
        return "vp"
    if "director" in t or "head of" in t:
        return "director"
    if "manager" in t or "lead" in t:
        return "manager"
    return "ic"


def compute_account_scores(
    account: Account,
    signals: list[AccountSignal],
) -> tuple[int, int]:
    """Deterministically compute (signal_score, icp_fit_score) in [0, 100]."""
    raw_signal = sum(s.weight * s.confidence for s in signals if s.verified)
    signal_score = min(100, round(raw_signal))

    if account.status == "suppressed":
        return signal_score, 0

    emp = account.employee_count or 0
    if 50 <= emp <= 2000:
        size_pts = 25
    elif 20 <= emp < 50 or 2000 < emp <= 5000:
        size_pts = 18
    elif emp > 0:
        size_pts = 10
    else:
        size_pts = 5

    industry_norm = (account.industry or "").strip().lower()
    if any(ind in industry_norm for ind in _TARGET_INDUSTRIES):
        ind_pts = 25
    elif industry_norm:
        ind_pts = 12
    else:
        ind_pts = 5

    stack_lower = {item.strip().lower() for item in (account.tech_stack_json or []) if item.strip()}
    overlap = len(stack_lower & _TARGET_STACK)
    if overlap > 0:
        stack_pts = min(20, 6 + overlap * 5)
    elif stack_lower:
        stack_pts = 8
    else:
        stack_pts = 4

    signal_pts = round(signal_score * 0.30)
    icp_score = max(0, min(100, size_pts + ind_pts + stack_pts + signal_pts))
    return signal_score, icp_score


async def recompute_account_scores(db: AsyncSession, account: Account) -> Account:
    """Refresh stored signal_score and icp_fit_score for an account."""
    signals = list(
        (
            await db.execute(
                select(AccountSignal).where(AccountSignal.account_id == account.id)
            )
        )
        .scalars()
        .all()
    )
    sig_score, icp_score = compute_account_scores(account, signals)
    account.signal_score = sig_score
    account.icp_fit_score = icp_score
    return account


def suppression_to_out(entry: SuppressionEntry) -> SuppressionEntryOut:
    """Serialize a SuppressionEntry ORM row."""
    return SuppressionEntryOut(
        id=entry.id,
        scope=entry.scope,
        value=entry.value,
        reason=entry.reason,
        source=entry.source,
        active=entry.active,
        created_by=entry.created_by,
        created_at=entry.created_at,
    )


async def check_account_suppression(db: AsyncSession, account: Account) -> tuple[bool, str | None]:
    """Return whether an account or its domain is actively suppressed."""
    if account.status == "suppressed":
        return True, f"Account '{account.domain}' is marked suppressed."
    domain = normalize_domain(account.domain)
    entry = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.scope == "domain",
                SuppressionEntry.value == domain,
                SuppressionEntry.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if entry is not None:
        return True, f"Domain suppression ({entry.value}): {entry.reason}"
    return False, None


async def check_contact_suppression(
    db: AsyncSession,
    contact: Contact,
    account: Account | None = None,
) -> tuple[bool, str | None]:
    """Enforce email, contact flag, and domain suppression checks."""
    if contact.do_not_contact or contact.status == "suppressed":
        return True, contact.opt_out_reason or "Contact opted out (do_not_contact)"

    resolved_account = account
    if resolved_account is None and contact.account_id:
        resolved_account = await db.get(Account, contact.account_id)

    if resolved_account is not None and resolved_account.status == "suppressed":
        return True, f"Account domain '{resolved_account.domain}' is suppressed."

    email_norm = normalize_email(contact.email)
    domains_to_check = {d for d in (extract_email_domain(email_norm),) if d}
    if resolved_account is not None and resolved_account.domain:
        domains_to_check.add(normalize_domain(resolved_account.domain))

    email_entry = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.scope == "email",
                SuppressionEntry.value == email_norm,
                SuppressionEntry.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if email_entry is not None:
        return True, f"Email suppression ({email_entry.value}): {email_entry.reason}"

    if domains_to_check:
        domain_entry = (
            await db.execute(
                select(SuppressionEntry).where(
                    SuppressionEntry.scope == "domain",
                    SuppressionEntry.value.in_(sorted(domains_to_check)),
                    SuppressionEntry.active.is_(True),
                )
            )
        ).scalars().first()
        if domain_entry is not None:
            return True, f"Domain suppression ({domain_entry.value}): {domain_entry.reason}"

    return False, None


async def apply_suppression(
    db: AsyncSession,
    *,
    scope: str,
    value: str,
    reason: str,
    source: str,
    actor: Actor,
    commit: bool = True,
) -> tuple[SuppressionEntry, int, int]:
    """Register suppression and immediately block matching contacts and pending touches."""
    norm_scope = scope.strip().lower()
    if norm_scope not in {"email", "domain"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Suppression scope must be 'email' or 'domain'.",
        )

    norm_val = normalize_email(value) if norm_scope == "email" else normalize_domain(value)
    if norm_scope == "email" and "@" not in norm_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email suppression requires a valid email address.",
        )
    if norm_scope == "domain" and "." not in norm_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Domain suppression requires a valid domain.",
        )

    clean_reason = reason.strip()
    entry = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.scope == norm_scope,
                SuppressionEntry.value == norm_val,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        entry = SuppressionEntry(
            scope=norm_scope,
            value=norm_val,
            reason=clean_reason,
            source=source.strip() or "manual",
            active=True,
            created_by=actor.email,
        )
        db.add(entry)
    else:
        entry.active = True
        entry.reason = clean_reason
        entry.source = source.strip() or entry.source
        entry.created_by = actor.email
    await db.flush()

    affected_account_ids: set[str] = set()
    if norm_scope == "domain":
        matching_accounts = list(
            (await db.execute(select(Account).where(Account.domain == norm_val))).scalars().all()
        )
        for acc in matching_accounts:
            acc.status = "suppressed"
            acc.icp_fit_score = 0
            affected_account_ids.add(acc.id)

    all_contacts = list((await db.execute(select(Contact))).scalars().all())
    matching_contacts: list[Contact] = []
    for c in all_contacts:
        is_email_match = norm_scope == "email" and normalize_email(c.email) == norm_val
        is_domain_match = norm_scope == "domain" and (
            extract_email_domain(c.email) == norm_val or c.account_id in affected_account_ids
        )
        if is_email_match or is_domain_match:
            matching_contacts.append(c)

    contacts_affected = 0
    matching_contact_ids: set[str] = set()
    for c in matching_contacts:
        matching_contact_ids.add(c.id)
        was_suppressed = c.do_not_contact and c.status == "suppressed"
        c.do_not_contact = True
        c.opt_out_reason = clean_reason
        if c.status != "merged":
            c.status = "suppressed"
        if not was_suppressed:
            contacts_affected += 1

    touches_blocked = 0
    if matching_contact_ids or affected_account_ids:
        sequences = list((await db.execute(select(OutreachSequence))).scalars().all())
        target_seq_ids = [
            seq.id
            for seq in sequences
            if seq.contact_id in matching_contact_ids or seq.account_id in affected_account_ids
        ]

        if target_seq_ids:
            touches = list(
                (
                    await db.execute(
                        select(SequenceTouch).where(
                            SequenceTouch.sequence_id.in_(target_seq_ids),
                            SequenceTouch.status.in_(
                                ["pending_approval", "approved", "rejected"]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            blocked_touch_ids: list[str] = []
            for touch in touches:
                touch.status = "blocked_suppressed"
                touches_blocked += 1
                blocked_touch_ids.append(touch.id)

            if blocked_touch_ids:
                pending_approvals = list(
                    (
                        await db.execute(
                            select(ApprovalRequest).where(
                                ApprovalRequest.entity_type == "sequence_touch",
                                ApprovalRequest.entity_id.in_(blocked_touch_ids),
                                ApprovalRequest.status == "pending",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for app_req in pending_approvals:
                    app_req.status = "rejected"
                    app_req.decided_by = actor.email
                    app_req.decision_notes = (
                        f"Auto-rejected due to {norm_scope} suppression: {clean_reason}"
                    )
                    app_req.decided_at = utcnow()

            for seq in sequences:
                if seq.id in target_seq_ids:
                    seq.status = "blocked_suppressed"

    await record_audit_event(
        db,
        event_type="prospecting.suppression_added",
        actor=actor,
        entity_type="suppression_entry",
        entity_id=entry.id,
        action="suppressed",
        details={
            "scope": norm_scope,
            "value": norm_val,
            "reason": clean_reason,
            "source": entry.source,
            "contacts_affected": contacts_affected,
            "touches_blocked": touches_blocked,
        },
    )
    if commit:
        await db.commit()
        await db.refresh(entry)
    return entry, contacts_affected, touches_blocked


async def deactivate_suppression(
    db: AsyncSession,
    *,
    entry_id: str,
    actor: Actor,
) -> SuppressionEntry:
    """Deactivate a suppression list entry (sales_manager/admin only)."""
    entry = await db.get(SuppressionEntry, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Suppression entry '{entry_id}' not found.",
        )

    entry.active = False

    if entry.scope == "domain":
        accounts = list(
            (await db.execute(select(Account).where(Account.domain == entry.value)))
            .scalars()
            .all()
        )
        for acc in accounts:
            if acc.status == "suppressed":
                acc.status = "active"
                await recompute_account_scores(db, acc)

    contacts = list((await db.execute(select(Contact))).scalars().all())
    for c in contacts:
        if c.status == "suppressed" and c.opt_out_reason == entry.reason:
            c.do_not_contact = False
            c.status = "active"
            still_suppressed, new_reason = await check_contact_suppression(db, c)
            if still_suppressed:
                c.do_not_contact = True
                c.status = "suppressed"
                c.opt_out_reason = new_reason
            else:
                c.opt_out_reason = None

    await record_audit_event(
        db,
        event_type="prospecting.suppression_deactivated",
        actor=actor,
        entity_type="suppression_entry",
        entity_id=entry.id,
        action="deactivated",
        details={"scope": entry.scope, "value": entry.value},
    )
    await db.commit()
    await db.refresh(entry)
    return entry
