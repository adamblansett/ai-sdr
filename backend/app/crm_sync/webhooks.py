import hashlib
import json
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.crm_sync.hygiene import validate_deal_hygiene
from app.crm_sync.schemas import CrmWebhookEventOut
from app.db.base import as_utc, quantize_money, utcnow
from app.db.models import Account, Contact, CrmDeal, CrmWebhookEvent, SuppressionEntry
from app.prospecting.suppression import (
    apply_suppression,
    check_contact_suppression,
    compute_account_scores,
    extract_email_domain,
    infer_seniority,
    normalize_domain,
    normalize_email,
)


def webhook_to_out(
    event: CrmWebhookEvent, *, duplicate_ignored: bool = False
) -> CrmWebhookEventOut:
    """Serialize a CrmWebhookEvent ORM row."""
    return CrmWebhookEventOut(
        id=event.id,
        idempotency_key=event.idempotency_key,
        source=event.source,
        event_type=event.event_type,
        payload_hash=event.payload_hash,
        status=event.status,
        result_summary=event.result_summary,
        duplicate_ignored=duplicate_ignored,
        received_at=event.received_at,
        processed_at=event.processed_at,
    )


async def _resolve_or_create_account(
    db: AsyncSession,
    *,
    account_id: str | None,
    domain: str,
    company_name: str,
    industry: str = "",
) -> Account:
    if account_id:
        acc = await db.get(Account, account_id)
        if acc is not None:
            return acc
    norm_domain = normalize_domain(domain)
    if "." not in norm_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook requires a valid account_id or account domain.",
        )
    acc = (
        await db.execute(select(Account).where(Account.domain == norm_domain))
    ).scalar_one_or_none()
    if acc is not None:
        return acc

    sup_domain = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.scope == "domain",
                SuppressionEntry.value == norm_domain,
                SuppressionEntry.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    acc = Account(
        name=company_name.strip() or norm_domain.split(".")[0].title(),
        domain=norm_domain,
        industry=industry.strip(),
        employee_count=0,
        tech_stack_json=[],
        status="suppressed" if sup_domain is not None else "active",
    )
    _, icp_score = compute_account_scores(acc, [])
    acc.icp_fit_score = icp_score
    db.add(acc)
    await db.flush()
    return acc


def _parse_optional_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    return date.fromisoformat(str(raw).strip()[:10])


def _parse_optional_datetime(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return as_utc(raw)
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return as_utc(datetime.fromisoformat(text))


async def process_crm_webhook(
    db: AsyncSession,
    *,
    source: str,
    idempotency_key: str,
    event_type: str,
    payload: dict[str, Any],
    actor: Actor,
) -> tuple[CrmWebhookEvent, bool]:
    """Process a CRM webhook event exactly once per idempotency_key."""
    clean_key = idempotency_key.strip()
    existing = (
        await db.execute(
            select(CrmWebhookEvent).where(CrmWebhookEvent.idempotency_key == clean_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    data = dict(payload.get("data") or {})
    summary = ""

    if event_type == "contact.upsert":
        email = normalize_email(str(data.get("email", "")))
        if "@" not in email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contact.upsert webhook requires data.email.",
            )
        domain = str(data.get("domain") or extract_email_domain(email))
        account = await _resolve_or_create_account(
            db,
            account_id=data.get("account_id"),
            domain=domain,
            company_name=str(data.get("company_name") or ""),
            industry=str(data.get("industry") or ""),
        )
        ext_id = str(data.get("external_id") or "").strip() or None
        contact: Contact | None = None
        if ext_id:
            contact = (
                await db.execute(
                    select(Contact).where(
                        Contact.crm_external_id == ext_id,
                        Contact.status != "merged",
                    )
                )
            ).scalar_one_or_none()
        if contact is None:
            contact = (
                await db.execute(
                    select(Contact).where(
                        Contact.account_id == account.id,
                        Contact.email == email,
                        Contact.status != "merged",
                    )
                )
            ).scalar_one_or_none()

        title = str(data.get("title") or "")
        if contact is None:
            contact = Contact(
                account_id=account.id,
                first_name=str(data.get("first_name") or email.split("@")[0].title()),
                last_name=str(data.get("last_name") or "Contact"),
                email=email,
                title=title,
                seniority=str(data.get("seniority") or infer_seniority(title)),
                department=str(data.get("department") or ""),
                phone=str(data.get("phone") or ""),
                linkedin_url=str(data.get("linkedin_url") or ""),
                crm_external_id=ext_id,
            )
            db.add(contact)
            await db.flush()
            action_taken = "created"
        else:
            if data.get("first_name"):
                contact.first_name = str(data["first_name"]).strip()
            if data.get("last_name"):
                contact.last_name = str(data["last_name"]).strip()
            if title:
                contact.title = title
                contact.seniority = str(data.get("seniority") or infer_seniority(title))
            if data.get("phone"):
                contact.phone = str(data["phone"]).strip()
            if ext_id:
                contact.crm_external_id = ext_id
            action_taken = "updated"

        suppressed, reason = await check_contact_suppression(db, contact, account)
        if suppressed:
            contact.do_not_contact = True
            contact.status = "suppressed"
            contact.opt_out_reason = reason
        summary = f"Contact {action_taken}: {contact.email}"

    elif event_type == "deal.upsert":
        ext_id = str(data.get("external_id") or "").strip() or None
        domain = str(data.get("domain") or "")
        account = await _resolve_or_create_account(
            db,
            account_id=data.get("account_id"),
            domain=domain or "unknown.example.com",
            company_name=str(data.get("company_name") or ""),
        )
        deal: CrmDeal | None = None
        if ext_id:
            deal = (
                await db.execute(select(CrmDeal).where(CrmDeal.external_id == ext_id))
            ).scalar_one_or_none()

        primary_contact_id = data.get("primary_contact_id")
        if not primary_contact_id and data.get("contact_email"):
            c_match = (
                await db.execute(
                    select(Contact).where(
                        Contact.email == normalize_email(str(data["contact_email"])),
                        Contact.status != "merged",
                    )
                )
            ).scalars().first()
            if c_match is not None:
                primary_contact_id = c_match.id

        if deal is None:
            deal = CrmDeal(
                external_id=ext_id,
                account_id=account.id,
                primary_contact_id=primary_contact_id,
                name=str(data.get("name") or f"{account.name} Opportunity"),
                stage=str(data.get("stage") or "discovery"),
                amount_usd=quantize_money(data.get("amount_usd") or 0),
                close_date=_parse_optional_date(data.get("close_date")),
                owner_email=str(data.get("owner_email") or actor.email),
                next_step=str(data.get("next_step") or ""),
                last_activity_at=_parse_optional_datetime(data.get("last_activity_at"))
                or utcnow(),
            )
            db.add(deal)
            action_taken = "created"
        else:
            if data.get("name"):
                deal.name = str(data["name"]).strip()
            if data.get("stage"):
                deal.stage = str(data["stage"]).strip()
            if data.get("amount_usd") is not None:
                deal.amount_usd = quantize_money(data["amount_usd"])
            if "close_date" in data:
                deal.close_date = _parse_optional_date(data.get("close_date"))
            if "next_step" in data:
                deal.next_step = str(data.get("next_step") or "")
            if primary_contact_id:
                deal.primary_contact_id = str(primary_contact_id)
            if data.get("last_activity_at"):
                deal.last_activity_at = (
                    _parse_optional_datetime(data.get("last_activity_at")) or utcnow()
                )
            action_taken = "updated"

        await db.flush()
        score, issues = await validate_deal_hygiene(db, deal)
        summary = f"Deal {action_taken}: {deal.name} (hygiene={score}, issues={len(issues)})"

    elif event_type == "contact.opt_out":
        email = str(data.get("email") or "").strip()
        domain = str(data.get("domain") or "").strip()
        reason = str(data.get("reason") or "CRM webhook opt-out").strip()
        if email:
            _, contacts_affected, touches_blocked = await apply_suppression(
                db,
                scope="email",
                value=email,
                reason=reason,
                source=f"webhook:{source}",
                actor=actor,
                commit=False,
            )
            summary = (
                f"Opt-out suppressed email '{normalize_email(email)}' "
                f"(contacts={contacts_affected}, touches_blocked={touches_blocked})"
            )
        elif domain:
            _, contacts_affected, touches_blocked = await apply_suppression(
                db,
                scope="domain",
                value=domain,
                reason=reason,
                source=f"webhook:{source}",
                actor=actor,
                commit=False,
            )
            summary = (
                f"Opt-out suppressed domain '{normalize_domain(domain)}' "
                f"(contacts={contacts_affected}, touches_blocked={touches_blocked})"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="contact.opt_out webhook requires data.email or data.domain.",
            )

    elif event_type == "activity.logged":
        deal_id = str(data.get("deal_id") or "").strip()
        ext_id = str(data.get("deal_external_id") or data.get("external_id") or "").strip()
        target_deal: CrmDeal | None = None
        if deal_id:
            target_deal = await db.get(CrmDeal, deal_id)
        elif ext_id:
            target_deal = (
                await db.execute(select(CrmDeal).where(CrmDeal.external_id == ext_id))
            ).scalar_one_or_none()
        if target_deal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="activity.logged webhook could not match a CRM deal.",
            )
        target_deal.last_activity_at = (
            _parse_optional_datetime(data.get("occurred_at")) or utcnow()
        )
        if data.get("next_step"):
            target_deal.next_step = str(data["next_step"]).strip()
        score, _ = await validate_deal_hygiene(db, target_deal)
        summary = f"Logged activity on '{target_deal.name}' (hygiene={score})"

    now = utcnow()
    event = CrmWebhookEvent(
        idempotency_key=clean_key,
        source=source.strip().lower(),
        event_type=event_type,
        payload_hash=payload_hash,
        payload_json=payload,
        status="processed",
        result_summary=summary[:300],
        received_at=now,
        processed_at=now,
    )
    db.add(event)
    await db.flush()

    await record_audit_event(
        db,
        event_type="crm.webhook_processed",
        actor=actor,
        entity_type="crm_webhook_event",
        entity_id=event.id,
        action="processed",
        details={
            "source": event.source,
            "event_type": event_type,
            "idempotency_key": clean_key,
            "summary": summary,
        },
    )
    await db.commit()
    await db.refresh(event)
    return event, False
