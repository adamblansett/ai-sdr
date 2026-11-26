from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.db.base import utcnow
from app.db.models import Contact, CrmDeal, InboundReply, OutreachSequence
from app.prospecting.suppression import apply_suppression, normalize_email
from app.sequences.schemas import InboundReplyOut

_UNSUBSCRIBE_KEYWORDS = (
    "unsubscribe",
    "opt out",
    "opt-out",
    "stop emailing",
    "remove me",
    "take me off",
    "do not contact",
)
_OOO_KEYWORDS = (
    "out of office",
    "ooo",
    "automatic reply",
    "auto-reply",
    "away from my desk",
    "on vacation",
    "returning on",
)
_INTERESTED_KEYWORDS = (
    "interested",
    "let's chat",
    "lets chat",
    "schedule",
    "calendar",
    "book a call",
    "send times",
    "open to a",
    "demo",
    "sounds good",
    "happy to connect",
)
_OBJECTION_KEYWORDS = (
    "not a priority",
    "no budget",
    "already have",
    "using a competitor",
    "not interested",
    "check back next year",
    "too expensive",
)


def classify_reply(subject: str, body: str) -> tuple[str, float]:
    """Deterministically classify an inbound prospect reply."""
    text = f"{subject}\n{body}".lower()
    if any(k in text for k in _UNSUBSCRIBE_KEYWORDS):
        return "unsubscribe", 0.98
    if any(k in text for k in _OOO_KEYWORDS):
        return "ooo", 0.94
    if any(k in text for k in _OBJECTION_KEYWORDS):
        return "objection", 0.88
    if any(k in text for k in _INTERESTED_KEYWORDS):
        return "interested", 0.91
    return "neutral", 0.72


def reply_to_out(reply: InboundReply) -> InboundReplyOut:
    """Serialize an InboundReply ORM row."""
    return InboundReplyOut(
        id=reply.id,
        sequence_id=reply.sequence_id,
        touch_id=reply.touch_id,
        contact_id=reply.contact_id,
        sender_email=reply.sender_email,
        subject=reply.subject,
        body=reply.body,
        classification=reply.classification,
        confidence=reply.confidence,
        auto_action_taken=reply.auto_action_taken,
        received_at=reply.received_at,
    )


async def ingest_inbound_reply(
    db: AsyncSession,
    *,
    sender_email: str,
    subject: str,
    body: str,
    sequence_id: str | None,
    touch_id: str | None,
    actor: Actor,
) -> InboundReply:
    """Classify an inbound reply and execute automated compliance/pipeline actions."""
    norm_email = normalize_email(sender_email)
    classification, confidence = classify_reply(subject, body)

    contact = (
        await db.execute(
            select(Contact)
            .where(Contact.email == norm_email, Contact.status != "merged")
            .limit(1)
        )
    ).scalar_one_or_none()

    resolved_sequence: OutreachSequence | None = None
    if sequence_id:
        resolved_sequence = await db.get(OutreachSequence, sequence_id)
    elif contact is not None:
        resolved_sequence = (
            await db.execute(
                select(OutreachSequence)
                .where(OutreachSequence.contact_id == contact.id)
                .order_by(OutreachSequence.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    auto_action = "Logged reply for SDR review."
    if classification == "unsubscribe":
        _, contacts_affected, touches_blocked = await apply_suppression(
            db,
            scope="email",
            value=norm_email,
            reason="Inbound reply opt-out detected",
            source="reply_classifier",
            actor=actor,
            commit=False,
        )
        auto_action = (
            f"Auto-suppressed {norm_email} "
            f"(contacts={contacts_affected}, touches_blocked={touches_blocked})."
        )
    elif classification in ("interested", "ooo"):
        if resolved_sequence is not None and resolved_sequence.status in (
            "pending_approval",
            "active",
        ):
            resolved_sequence.status = "paused"
        if contact is not None:
            open_deals = list(
                (
                    await db.execute(
                        select(CrmDeal).where(
                            CrmDeal.account_id == contact.account_id,
                            CrmDeal.stage.notin_(["closed_won", "closed_lost"]),
                        )
                    )
                )
                .scalars()
                .all()
            )
            now = utcnow()
            for deal in open_deals:
                deal.last_activity_at = now
        auto_action = (
            "Paused sequence & updated deal activity for interested lead."
            if classification == "interested"
            else "Paused sequence due to out-of-office auto-reply."
        )
    elif classification == "objection" and resolved_sequence is not None:
        if resolved_sequence.status in ("pending_approval", "active"):
            resolved_sequence.status = "paused"
        auto_action = "Paused sequence after objection; flagged for manager coaching."

    reply = InboundReply(
        sequence_id=resolved_sequence.id if resolved_sequence else None,
        touch_id=touch_id,
        contact_id=contact.id if contact else None,
        sender_email=norm_email,
        subject=subject.strip()[:300],
        body=body.strip(),
        classification=classification,
        confidence=confidence,
        auto_action_taken=auto_action[:240],
        received_at=utcnow(),
    )
    db.add(reply)
    await db.flush()

    await record_audit_event(
        db,
        event_type="sequence.reply_classified",
        actor=actor,
        entity_type="inbound_reply",
        entity_id=reply.id,
        action=classification,
        details={
            "sender_email": norm_email,
            "classification": classification,
            "confidence": confidence,
            "auto_action": auto_action,
        },
    )
    await db.commit()
    await db.refresh(reply)
    return reply
