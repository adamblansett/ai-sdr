import csv
import io
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.db.base import quantize_money, utcnow
from app.db.models import (
    Account,
    AccountSignal,
    ApprovalRequest,
    Contact,
    OutreachSequence,
    SequenceTouch,
    SuppressionEntry,
)
from app.llm.router import LLMRouter
from app.prospecting.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountResearchOut,
    ContactCreateIn,
    ContactOut,
    CsvImportOut,
    SignalCreateIn,
    SuppressionEntryOut,
)

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


def account_to_out(account: Account) -> AccountOut:
    """Serialize an Account ORM row into AccountOut."""
    return AccountOut(
        id=account.id,
        name=account.name,
        domain=account.domain,
        industry=account.industry,
        employee_count=account.employee_count,
        annual_revenue_usd=float(account.annual_revenue_usd),
        headquarters=account.headquarters,
        tech_stack=list(account.tech_stack_json or []),
        icp_fit_score=account.icp_fit_score,
        signal_score=account.signal_score,
        research_summary=account.research_summary,
        status=account.status,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


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


async def contact_to_out(
    db: AsyncSession,
    contact: Contact,
    account: Account | None = None,
) -> ContactOut:
    """Serialize a Contact with computed suppression status."""
    suppressed, reason = await check_contact_suppression(db, contact, account)
    return ContactOut(
        id=contact.id,
        account_id=contact.account_id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        email=contact.email,
        title=contact.title,
        seniority=contact.seniority,
        department=contact.department,
        phone=contact.phone,
        linkedin_url=contact.linkedin_url,
        do_not_contact=contact.do_not_contact,
        opt_out_reason=contact.opt_out_reason,
        status=contact.status,
        merged_into_id=contact.merged_into_id,
        crm_external_id=contact.crm_external_id,
        is_suppressed=suppressed,
        suppression_reason=reason,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )


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


async def create_account(
    db: AsyncSession,
    *,
    payload: AccountCreateIn,
    actor: Actor,
) -> Account:
    """Create a new target account after enforcing domain uniqueness & suppression."""
    domain = normalize_domain(payload.domain)
    if "." not in domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account domain must be a valid domain name.",
        )

    existing = (
        await db.execute(select(Account).where(Account.domain == domain))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Account with domain '{domain}' already exists.",
        )

    suppressed_domain = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.scope == "domain",
                SuppressionEntry.value == domain,
                SuppressionEntry.active.is_(True),
            )
        )
    ).scalar_one_or_none()

    account = Account(
        name=payload.name.strip(),
        domain=domain,
        industry=payload.industry.strip(),
        employee_count=payload.employee_count,
        annual_revenue_usd=quantize_money(payload.annual_revenue_usd),
        headquarters=payload.headquarters.strip(),
        tech_stack_json=[t.strip() for t in payload.tech_stack if t.strip()],
        research_summary=payload.research_summary.strip(),
        status="suppressed" if suppressed_domain is not None else "active",
    )
    _, icp_score = compute_account_scores(account, [])
    account.icp_fit_score = icp_score
    account.signal_score = 0

    db.add(account)
    await db.flush()
    await record_audit_event(
        db,
        event_type="prospecting.account_created",
        actor=actor,
        entity_type="account",
        entity_id=account.id,
        action="created",
        details={"domain": account.domain, "status": account.status},
    )
    await db.commit()
    await db.refresh(account)
    return account


async def add_account_signal(
    db: AsyncSession,
    *,
    account_id: str,
    payload: SignalCreateIn,
    actor: Actor,
) -> AccountSignal:
    """Attach a public buying signal to an account and update scores."""
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )

    signal = AccountSignal(
        account_id=account.id,
        signal_type=payload.signal_type.strip().lower(),
        title=payload.title.strip(),
        summary=payload.summary.strip(),
        evidence_excerpt=payload.evidence_excerpt.strip() or payload.summary.strip(),
        source_url=payload.source_url.strip(),
        confidence=payload.confidence,
        weight=payload.weight,
        observed_at=payload.observed_at or utcnow(),
        verified=payload.verified,
    )
    db.add(signal)
    await db.flush()

    await recompute_account_scores(db, account)
    await record_audit_event(
        db,
        event_type="prospecting.signal_added",
        actor=actor,
        entity_type="account_signal",
        entity_id=signal.id,
        action="created",
        details={
            "account_id": account.id,
            "signal_type": signal.signal_type,
            "verified": signal.verified,
            "weight": signal.weight,
        },
    )
    await db.commit()
    await db.refresh(signal)
    return signal


async def synthesize_account_research(
    db: AsyncSession,
    *,
    account_id: str,
    llm_router: LLMRouter,
    actor: Actor,
) -> AccountResearchOut:
    """Synthesize an account research summary from verified public signals."""
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )

    signals = list(
        (
            await db.execute(
                select(AccountSignal)
                .where(AccountSignal.account_id == account.id)
                .order_by(AccountSignal.observed_at.desc())
            )
        )
        .scalars()
        .all()
    )
    verified_text = (
        "; ".join(
            f"{s.signal_type}: {s.title} ({s.source_url or 'public'})"
            for s in signals
            if s.verified
        )
        or "No verified public signals logged yet"
    )
    stack_text = ", ".join(account.tech_stack_json or []) or "Unknown stack"

    prompt = (
        f"Account: {account.name}\n"
        f"Domain: {account.domain}\n"
        f"Industry: {account.industry or 'B2B Technology'}\n"
        f"Employees: {account.employee_count}\n"
        f"Tech Stack: {stack_text}\n"
        f"Verified Signals: {verified_text}"
    )
    llm_res = await llm_router.generate(
        prompt=prompt,
        system_prompt="Summarize B2B account research concisely from verified facts only.",
        task_type="account_research",
    )
    account.research_summary = llm_res.content
    await recompute_account_scores(db, account)

    await record_audit_event(
        db,
        event_type="prospecting.account_researched",
        actor=actor,
        entity_type="account",
        entity_id=account.id,
        action="researched",
        details={
            "llm_provider": llm_res.provider,
            "llm_model": llm_res.model,
            "pii_redacted": llm_res.pii_redacted,
            "signal_count": len(signals),
        },
    )
    await db.commit()
    await db.refresh(account)
    return AccountResearchOut(
        account=account_to_out(account),
        llm_provider=llm_res.provider,
        llm_model=llm_res.model,
        pii_redacted=llm_res.pii_redacted,
    )


async def create_contact(
    db: AsyncSession,
    *,
    payload: ContactCreateIn,
    actor: Actor,
) -> Contact:
    """Create a contact under an account, automatically enforcing existing suppressions."""
    account = await db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{payload.account_id}' not found.",
        )

    email_norm = normalize_email(payload.email)
    if "@" not in email_norm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contact email must be valid.",
        )

    seniority = payload.seniority or infer_seniority(payload.title)
    contact = Contact(
        account_id=account.id,
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        email=email_norm,
        title=payload.title.strip(),
        seniority=seniority,
        department=payload.department.strip(),
        phone=payload.phone.strip(),
        linkedin_url=payload.linkedin_url.strip(),
        crm_external_id=payload.crm_external_id.strip() if payload.crm_external_id else None,
    )
    db.add(contact)
    await db.flush()

    suppressed, reason = await check_contact_suppression(db, contact, account)
    if suppressed:
        contact.do_not_contact = True
        contact.status = "suppressed"
        contact.opt_out_reason = reason

    await record_audit_event(
        db,
        event_type="prospecting.contact_created",
        actor=actor,
        entity_type="contact",
        entity_id=contact.id,
        action="created",
        details={
            "account_id": account.id,
            "email_domain": extract_email_domain(email_norm),
            "suppressed": suppressed,
        },
    )
    await db.commit()
    await db.refresh(contact)
    return contact


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
        seq_stmt = select(OutreachSequence)
        sequences = list((await db.execute(seq_stmt)).scalars().all())
        target_seq_ids: list[str] = []
        for seq in sequences:
            if seq.contact_id in matching_contact_ids or seq.account_id in affected_account_ids:
                target_seq_ids.append(seq.id)

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


async def import_contacts_csv(
    db: AsyncSession,
    *,
    csv_text: str,
    actor: Actor,
) -> CsvImportOut:
    """Parse CSV prospect rows, link/create accounts by domain, and flag suppressions."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames or "email" not in {f.strip().lower() for f in reader.fieldnames}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must include a header row with at least an 'email' column.",
        )

    accounts_created = 0
    contacts_created = 0
    contacts_skipped = 0
    suppressed_flagged = 0
    errors: list[str] = []

    for row_idx, raw_row in enumerate(reader, start=2):
        row = {str(k).strip().lower(): (v or "").strip() for k, v in raw_row.items() if k}
        email = normalize_email(row.get("email", ""))
        if "@" not in email:
            errors.append(f"Row {row_idx}: invalid or missing email.")
            contacts_skipped += 1
            continue

        raw_domain = row.get("domain") or extract_email_domain(email)
        domain = normalize_domain(raw_domain)
        if "." not in domain:
            errors.append(f"Row {row_idx}: invalid domain for '{email}'.")
            contacts_skipped += 1
            continue

        account = (
            await db.execute(select(Account).where(Account.domain == domain))
        ).scalar_one_or_none()
        if account is None:
            sup_domain = (
                await db.execute(
                    select(SuppressionEntry).where(
                        SuppressionEntry.scope == "domain",
                        SuppressionEntry.value == domain,
                        SuppressionEntry.active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            company_name = (
                row.get("company_name") or row.get("company") or domain.split(".")[0].title()
            )
            account = Account(
                name=company_name,
                domain=domain,
                industry=row.get("industry", ""),
                employee_count=0,
                tech_stack_json=[],
                status="suppressed" if sup_domain is not None else "active",
            )
            _, icp_score = compute_account_scores(account, [])
            account.icp_fit_score = icp_score
            db.add(account)
            await db.flush()
            accounts_created += 1

        existing_contact = (
            await db.execute(
                select(Contact).where(
                    Contact.account_id == account.id,
                    Contact.email == email,
                    Contact.status != "merged",
                )
            )
        ).scalar_one_or_none()
        if existing_contact is not None:
            contacts_skipped += 1
            continue

        first_name = row.get("first_name") or email.split("@", 1)[0].split(".")[0].title()
        last_name = row.get("last_name") or "Contact"
        title = row.get("title", "")
        contact = Contact(
            account_id=account.id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            title=title,
            seniority=infer_seniority(title),
            department=row.get("department", ""),
            phone=row.get("phone", ""),
        )
        db.add(contact)
        await db.flush()

        suppressed, reason = await check_contact_suppression(db, contact, account)
        if suppressed:
            contact.do_not_contact = True
            contact.status = "suppressed"
            contact.opt_out_reason = reason
            suppressed_flagged += 1

        contacts_created += 1

    await record_audit_event(
        db,
        event_type="prospecting.contacts_imported",
        actor=actor,
        entity_type="contact_batch",
        entity_id="csv-import",
        action="imported",
        details={
            "accounts_created": accounts_created,
            "contacts_created": contacts_created,
            "contacts_skipped": contacts_skipped,
            "suppressed_flagged": suppressed_flagged,
        },
    )
    await db.commit()
    return CsvImportOut(
        accounts_created=accounts_created,
        contacts_created=contacts_created,
        contacts_skipped=contacts_skipped,
        suppressed_flagged=suppressed_flagged,
        errors=errors,
    )
