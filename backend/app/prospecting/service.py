import csv
import io

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.core.config import get_settings
from app.db.base import quantize_money, utcnow
from app.db.models import Account, AccountSignal, Contact, SuppressionEntry
from app.llm.router import LLMRouter
from app.prospecting.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountResearchOut,
    ContactCreateIn,
    ContactOut,
    CsvImportOut,
    SignalCreateIn,
)
from app.prospecting.suppression import (
    _TARGET_INDUSTRIES,
    _TARGET_STACK,
    apply_suppression,
    check_account_suppression,
    check_contact_suppression,
    compute_account_scores,
    deactivate_suppression,
    extract_email_domain,
    infer_seniority,
    normalize_domain,
    normalize_email,
    recompute_account_scores,
    suppression_to_out,
)
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.service import index_knowledge_chunk

__all__ = [
    "_TARGET_INDUSTRIES",
    "_TARGET_STACK",
    "account_to_out",
    "add_account_signal",
    "apply_suppression",
    "check_account_suppression",
    "check_contact_suppression",
    "compute_account_scores",
    "contact_to_out",
    "contacts_to_out",
    "create_account",
    "create_contact",
    "deactivate_suppression",
    "extract_email_domain",
    "import_contacts_csv",
    "infer_seniority",
    "normalize_domain",
    "normalize_email",
    "recompute_account_scores",
    "suppression_to_out",
    "synthesize_account_research",
]


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


def _serialize_contact(
    contact: Contact,
    suppressed: bool,
    reason: str | None,
) -> ContactOut:
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


async def contact_to_out(
    db: AsyncSession,
    contact: Contact,
    account: Account | None = None,
) -> ContactOut:
    """Serialize a single Contact with computed suppression status."""
    suppressed, reason = await check_contact_suppression(db, contact, account)
    return _serialize_contact(contact, suppressed, reason)


async def contacts_to_out(
    db: AsyncSession,
    contacts: list[Contact],
) -> list[ContactOut]:
    """Bulk serialize Contacts with O(1) batched suppression lookups (no N+1)."""
    if not contacts:
        return []

    account_ids = sorted({c.account_id for c in contacts if c.account_id})
    accounts_map: dict[str, Account] = {}
    if account_ids:
        acc_rows = list(
            (await db.execute(select(Account).where(Account.id.in_(account_ids))))
            .scalars()
            .all()
        )
        accounts_map = {a.id: a for a in acc_rows}

    active_suppressions = list(
        (
            await db.execute(
                select(SuppressionEntry).where(SuppressionEntry.active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    email_sup = {
        s.value: s.reason for s in active_suppressions if s.scope == "email"
    }
    domain_sup = {
        s.value: s.reason for s in active_suppressions if s.scope == "domain"
    }

    results: list[ContactOut] = []
    for c in contacts:
        if c.do_not_contact or c.status == "suppressed":
            results.append(
                _serialize_contact(
                    c, True, c.opt_out_reason or "Contact opted out (do_not_contact)"
                )
            )
            continue

        acc = accounts_map.get(c.account_id)
        if acc is not None and acc.status == "suppressed":
            results.append(
                _serialize_contact(
                    c, True, f"Account domain '{acc.domain}' is suppressed."
                )
            )
            continue

        email_norm = normalize_email(c.email)
        if email_norm in email_sup:
            results.append(
                _serialize_contact(
                    c, True, f"Email suppression ({email_norm}): {email_sup[email_norm]}"
                )
            )
            continue

        matched_domain_reason: str | None = None
        for dom in (extract_email_domain(email_norm), normalize_domain(acc.domain) if acc else ""):
            if dom and dom in domain_sup:
                matched_domain_reason = f"Domain suppression ({dom}): {domain_sup[dom]}"
                break

        results.append(
            _serialize_contact(c, matched_domain_reason is not None, matched_domain_reason)
        )
    return results


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
    embedding_service: EmbeddingService | None = None,
) -> AccountSignal:
    """Attach a public buying signal, index it for semantic search, and update scores."""
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

    if signal.verified:
        emb_service = embedding_service or EmbeddingService(get_settings())
        chunk_body = signal.evidence_excerpt or signal.summary or signal.title
        await index_knowledge_chunk(
            db,
            account_id=account.id,
            source_type="signal",
            source_ref_id=signal.id,
            title=signal.title,
            content=chunk_body,
            source_url=signal.source_url,
            embedding_service=emb_service,
            actor=actor,
            commit=False,
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
