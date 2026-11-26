import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.core.config import get_settings
from app.db.models import Account, AccountSignal, Contact, QualificationRecord
from app.llm.router import LLMRouter
from app.prospecting.suppression import (
    _TARGET_INDUSTRIES,
    _TARGET_STACK,
    check_account_suppression,
    check_contact_suppression,
)
from app.qualification.schemas import (
    EvidenceCitationOut,
    QualificationOut,
    RubricDimensionOut,
    RubricWeightsIn,
)
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.service import search_knowledge


def qualification_to_out(record: QualificationRecord) -> QualificationOut:
    """Serialize a QualificationRecord ORM model into QualificationOut."""
    return QualificationOut(
        id=record.id,
        account_id=record.account_id,
        contact_id=record.contact_id,
        icp_score=record.icp_score,
        intent_tier=record.intent_tier,
        grade=record.grade,
        bant=dict(record.bant_json or {}),
        meddic=dict(record.meddic_json or {}),
        rubric_breakdown=[
            RubricDimensionOut(**item) for item in (record.rubric_breakdown_json or [])
        ],
        evidence_citations=[
            EvidenceCitationOut(**item) for item in (record.evidence_citations_json or [])
        ],
        rationale=record.rationale,
        llm_provider=record.llm_provider,
        llm_model=record.llm_model,
        pii_redacted=record.pii_redacted,
        created_by=record.created_by,
        created_at=record.created_at,
    )


def _extract_matching_sentence(text: str, keywords: tuple[str, ...]) -> str | None:
    if not text.strip():
        return None
    segments = [seg.strip() for seg in re.split(r"(?<=[.!?;])\s+|\n+", text) if seg.strip()]
    for seg in segments:
        lower = seg.lower()
        if any(kw in lower for kw in keywords):
            return seg[:220]
    return None


def _extract_bant_meddic(
    *,
    account: Account,
    contact: Contact | None,
    signals: list[AccountSignal],
    discovery_notes: str,
) -> tuple[dict[str, str], dict[str, str]]:
    notes = discovery_notes.strip()
    signal_corpus = " ".join(f"{s.title}. {s.summary}" for s in signals)
    combined = f"{notes}\n{signal_corpus}".strip()

    budget = _extract_matching_sentence(
        combined, ("budget", "series ", "funding", "raised", "allocated", "approved", "$")
    )
    if not budget:
        if account.annual_revenue_usd > 0:
            budget = (
                f"Inferred capacity from ~${int(account.annual_revenue_usd):,} annual revenue; "
                "requires explicit budget confirmation."
            )
        else:
            budget = "Unconfirmed — verify FY outbound/RevOps budget allocation on discovery call."

    if contact is not None:
        role_label = contact.title or contact.seniority
        authority = (
            f"{contact.first_name} {contact.last_name} ({role_label}, {contact.seniority}) "
            + (
                "holds executive/budget authority."
                if contact.seniority in ("c_level", "vp")
                else "is a functional influencer/evaluator."
            )
        )
    else:
        authority = "No primary contact linked yet; target VP Sales / CRO / Head of RevOps."

    need = _extract_matching_sentence(
        combined, ("need", "pain", "manual", "bottleneck", "slow", "pipeline", "outbound", "crm")
    )
    if not need:
        need = (
            signals[0].summary[:200]
            if signals
            else "Potential outbound & CRM hygiene automation fit based on company stage."
        )

    timeline = _extract_matching_sentence(
        combined,
        ("q1", "q2", "q3", "q4", "quarter", "week", "month", "day", "deadline", "this year"),
    )
    if not timeline:
        timeline = (
            "Near-term trigger window (~30-90 days) inferred from active signals; "
            "confirm target go-live."
        )

    metrics = _extract_matching_sentence(
        combined, ("%", "roi", "arr", "pipeline", "conversion", "reply", "hours", "meetings", "sql")
    ) or "Target KPIs: qualified meetings booked, sequence reply rate, and CRM hygiene score."

    if contact is not None and contact.seniority in ("c_level", "vp"):
        role_title = contact.title or contact.seniority
        economic_buyer = f"{contact.first_name} {contact.last_name} ({role_title})"
    else:
        economic_buyer = "CRO / VP of Sales (confirm executive sponsor during discovery)"

    decision_criteria = _extract_matching_sentence(
        combined,
        (
            "criteria",
            "security",
            "soc",
            "pii",
            "compliance",
            "self-host",
            "ollama",
            "gdpr",
            "hipaa",
        ),
    ) or "Self-hosted data control, PII redaction, human-approved outbound, and CRM sync fidelity."

    decision_process = _extract_matching_sentence(
        combined, ("process", "procurement", "security review", "pilot", "legal", "approve")
    ) or "Discovery -> security/compliance check -> 2-week pilot -> commercial sign-off."

    identify_pain = need

    if contact is not None:
        champion = (
            f"{contact.first_name} {contact.last_name} ({contact.title or contact.seniority})"
            if contact.seniority in ("director", "manager", "vp")
            else f"Engage RevOps / SDR Lead alongside {contact.first_name} {contact.last_name}"
        )
    else:
        champion = "Identify Head of SDR / RevOps Manager as internal champion."

    bant = {
        "budget": budget,
        "authority": authority,
        "need": need,
        "timeline": timeline,
    }
    meddic = {
        "metrics": metrics,
        "economic_buyer": economic_buyer,
        "decision_criteria": decision_criteria,
        "decision_process": decision_process,
        "identify_pain": identify_pain,
        "champion": champion,
    }
    return bant, meddic


async def evaluate_lead(
    db: AsyncSession,
    *,
    account_id: str,
    contact_id: str | None,
    discovery_notes: str,
    rubric_weights: RubricWeightsIn | None,
    llm_router: LLMRouter,
    actor: Actor,
    embedding_service: EmbeddingService | None = None,
) -> QualificationRecord:
    """Evaluate ICP fit, buying intent, and BANT/MEDDIC with verified signal citations."""
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )

    contact: Contact | None = None
    if contact_id:
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

    suppressed, sup_reason = await check_account_suppression(db, account)
    if not suppressed and contact is not None:
        suppressed, sup_reason = await check_contact_suppression(db, contact, account)

    citations = [
        {
            "signal_id": sig.id,
            "signal_type": sig.signal_type,
            "title": sig.title,
            "source_url": sig.source_url,
            "excerpt": (sig.evidence_excerpt or sig.summary)[:260],
            "confidence": sig.confidence,
        }
        for sig in signals
    ]
    cited_ids = {sig.id for sig in signals}
    emb_svc = embedding_service or EmbeddingService(get_settings())
    semantic_hits = await search_knowledge(
        db,
        query=f"{account.name} {account.industry} {discovery_notes[:300]}",
        account_id=account.id,
        top_k=2,
        min_score=0.05,
        embedding_service=emb_svc,
    )
    for hit in semantic_hits:
        ref_id = hit.chunk.source_ref_id or hit.chunk.id
        if ref_id not in cited_ids:
            cited_ids.add(ref_id)
            citations.append(
                {
                    "signal_id": ref_id,
                    "signal_type": hit.chunk.source_type,
                    "title": hit.chunk.title,
                    "source_url": hit.chunk.source_url,
                    "excerpt": hit.chunk.content[:260],
                    "confidence": hit.score,
                }
            )

    if suppressed:
        account.icp_fit_score = 0
        record = QualificationRecord(
            account_id=account.id,
            contact_id=contact.id if contact else None,
            icp_score=0,
            intent_tier="disqualified",
            grade="D",
            bant_json={
                "budget": "Blocked — suppressed entity",
                "authority": "Do not engage",
                "need": "Disqualified under suppression policy",
                "timeline": "N/A",
            },
            meddic_json={
                "metrics": "N/A",
                "economic_buyer": "Do not contact",
                "decision_criteria": "Compliance block active",
                "decision_process": "Blocked",
                "identify_pain": sup_reason or "Active suppression entry",
                "champion": "N/A",
            },
            rubric_breakdown_json=[
                {
                    "dimension": "compliance_gate",
                    "weight": 100,
                    "score": 0,
                    "max_score": 100,
                    "reason": sup_reason or "Active suppression/opt-out rule enforced.",
                }
            ],
            evidence_citations_json=citations,
            rationale=f"Automatically disqualified due to active suppression: {sup_reason}",
            llm_provider="policy-gate",
            llm_model="compliance-rule-v1",
            pii_redacted=False,
            created_by=actor.email,
        )
        db.add(record)
        await db.flush()
        await record_audit_event(
            db,
            event_type="qualification.evaluated",
            actor=actor,
            entity_type="qualification",
            entity_id=record.id,
            action="disqualified_suppressed",
            details={"account_id": account.id, "icp_score": 0, "reason": sup_reason},
        )
        await db.commit()
        await db.refresh(record)
        return record

    weights = rubric_weights or RubricWeightsIn()
    emp = account.employee_count
    if 50 <= emp <= 2000:
        size_score = 95
        size_reason = f"{emp} employees matches ideal mid-market/enterprise B2B sweet spot."
    elif 20 <= emp < 50 or 2000 < emp <= 5000:
        size_score = 75
        size_reason = f"{emp} employees falls in adjacent target band."
    elif emp > 0:
        size_score = 45
        size_reason = f"{emp} employees is outside primary target headcount band."
    else:
        size_score = 25
        size_reason = "Employee headcount not yet enriched."

    ind_lower = account.industry.strip().lower()
    if any(t in ind_lower for t in _TARGET_INDUSTRIES):
        ind_score = 92
        ind_reason = f"Industry '{account.industry}' is a high-fit ICP vertical."
    elif ind_lower:
        ind_score = 55
        ind_reason = f"Industry '{account.industry}' has moderate outbound relevance."
    else:
        ind_score = 25
        ind_reason = "Industry classification missing."

    stack_lower = {item.strip().lower() for item in (account.tech_stack_json or []) if item.strip()}
    overlap = sorted(stack_lower & _TARGET_STACK)
    if len(overlap) >= 3:
        stack_score = 95
        stack_reason = f"Strong stack overlap: {', '.join(overlap)}."
    elif len(overlap) == 2:
        stack_score = 80
        stack_reason = f"Good stack overlap: {', '.join(overlap)}."
    elif len(overlap) == 1:
        stack_score = 65
        stack_reason = f"Compatible tool detected: {overlap[0]}."
    elif stack_lower:
        stack_score = 45
        stack_reason = "Tech stack populated without core CRM/warehouse overlap."
    else:
        stack_score = 25
        stack_reason = "Tech stack not yet enriched."

    raw_sig = sum(s.weight * s.confidence for s in signals)
    notes_lower = discovery_notes.lower()
    urgency_cues = ("q1", "q2", "q3", "q4", "budget", "urgent", "pilot")
    urgency_bonus = 15 if any(k in notes_lower for k in urgency_cues) else 0
    if signals:
        sig_score = min(100, max(35, round(raw_sig * 1.45) + urgency_bonus))
        sig_reason = f"{len(signals)} verified signal(s) totaling weighted score {sig_score}/100."
    else:
        sig_score = min(45, 15 + urgency_bonus)
        sig_reason = "No verified external buying signals logged yet."

    if contact is not None:
        seniority_map = {
            "c_level": (100, f"Executive buyer ({contact.title or 'C-Level'})."),
            "vp": (90, f"VP-level decision maker ({contact.title or 'VP'})."),
            "director": (75, f"Director-level champion/evaluator ({contact.title or 'Director'})."),
            "manager": (55, f"Manager-level stakeholder ({contact.title or 'Manager'})."),
            "ic": (35, f"Individual contributor ({contact.title or 'IC'})."),
        }
        auth_score, auth_reason = seniority_map.get(
            contact.seniority, (50, "Standard contact seniority.")
        )
    else:
        auth_score = 50
        auth_reason = "No specific contact attached; scored at account baseline."

    dimensions = [
        ("company_size", weights.company_size, size_score, size_reason),
        ("industry_fit", weights.industry_fit, ind_score, ind_reason),
        ("tech_stack_fit", weights.tech_stack_fit, stack_score, stack_reason),
        ("buying_signals", weights.buying_signals, sig_score, sig_reason),
        ("buyer_authority", weights.buyer_authority, auth_score, auth_reason),
    ]
    total_weight = sum(w for _, w, _, _ in dimensions) or 1
    weighted_sum = sum(w * s for _, w, s, _ in dimensions)
    icp_score = max(0, min(100, round(weighted_sum / total_weight)))

    if icp_score >= 75:
        intent_tier = "high"
    elif icp_score >= 50:
        intent_tier = "medium"
    elif icp_score >= 30:
        intent_tier = "low"
    else:
        intent_tier = "disqualified"

    if icp_score >= 80:
        grade = "A"
    elif icp_score >= 65:
        grade = "B"
    elif icp_score >= 45:
        grade = "C"
    else:
        grade = "D"

    bant, meddic = _extract_bant_meddic(
        account=account,
        contact=contact,
        signals=signals,
        discovery_notes=discovery_notes,
    )

    rubric_breakdown = [
        {
            "dimension": name,
            "weight": w,
            "score": sc,
            "max_score": 100,
            "reason": rsn,
        }
        for name, w, sc, rsn in dimensions
    ]

    signals_brief = (
        "; ".join(f"{s.signal_type}: {s.title}" for s in signals[:4])
        or "Account profile only"
    )
    prompt = (
        f"Account: {account.name}\n"
        f"ICP Score: {icp_score}\n"
        f"Intent Tier: {intent_tier}\n"
        f"Signals: {signals_brief}\n"
        f"Discovery Notes: {discovery_notes[:600]}"
    )
    llm_res = await llm_router.generate(
        prompt=prompt,
        system_prompt="Provide a concise, evidence-grounded B2B lead qualification rationale.",
        task_type="lead_qualification",
    )

    account.icp_fit_score = icp_score
    record = QualificationRecord(
        account_id=account.id,
        contact_id=contact.id if contact else None,
        icp_score=icp_score,
        intent_tier=intent_tier,
        grade=grade,
        bant_json=bant,
        meddic_json=meddic,
        rubric_breakdown_json=rubric_breakdown,
        evidence_citations_json=citations,
        rationale=llm_res.content,
        llm_provider=llm_res.provider,
        llm_model=llm_res.model,
        pii_redacted=llm_res.pii_redacted,
        created_by=actor.email,
    )
    db.add(record)
    await db.flush()

    await record_audit_event(
        db,
        event_type="qualification.evaluated",
        actor=actor,
        entity_type="qualification",
        entity_id=record.id,
        action="evaluated",
        details={
            "account_id": account.id,
            "icp_score": icp_score,
            "intent_tier": intent_tier,
            "grade": grade,
            "citations_count": len(citations),
            "llm_provider": llm_res.provider,
        },
    )
    await db.commit()
    await db.refresh(record)
    return record


def make_rationale_summary(record: QualificationRecord) -> dict[str, Any]:
    """Return compact qualification metadata for downstream sequence grounding."""
    return {
        "icp_score": record.icp_score,
        "intent_tier": record.intent_tier,
        "grade": record.grade,
        "need": record.bant_json.get("need", ""),
    }
