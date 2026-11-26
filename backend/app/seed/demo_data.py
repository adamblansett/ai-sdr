import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor, hash_password
from app.core.config import Settings
from app.crm_sync.connectors import push_crm_sync
from app.crm_sync.hygiene import scan_duplicate_contacts, validate_deal_hygiene
from app.db.base import utcnow
from app.db.models import (
    Account,
    AccountSignal,
    ApprovalRequest,
    AuditEvent,
    BackgroundJob,
    Contact,
    CrmDeal,
    CrmSyncJob,
    CrmWebhookEvent,
    DuplicateMergeCandidate,
    InboundReply,
    KnowledgeChunk,
    OutreachSequence,
    QualificationRecord,
    SequenceTouch,
    SuppressionEntry,
    User,
)
from app.llm.router import LLMRouter
from app.prospecting.service import compute_account_scores
from app.qualification.engine import evaluate_lead
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.service import index_knowledge_chunk
from app.sequences.composer import generate_sequence
from app.sequences.replies import ingest_inbound_reply
from app.workers.tasks import dispatch_background_job


async def seed_demo_dataset(
    db: AsyncSession,
    *,
    llm_router: LLMRouter,
    settings: Settings,
    actor: Actor,
    reset: bool = False,
) -> dict[str, Any]:
    """Populate a realistic end-to-end AI SDR dataset idempotently."""
    _ = settings
    if reset:
        for model in (
            AuditEvent,
            ApprovalRequest,
            BackgroundJob,
            CrmSyncJob,
            InboundReply,
            KnowledgeChunk,
            CrmWebhookEvent,
            DuplicateMergeCandidate,
            CrmDeal,
            SequenceTouch,
            OutreachSequence,
            QualificationRecord,
            AccountSignal,
            Contact,
            SuppressionEntry,
            Account,
            User,
        ):
            await db.execute(delete(model))
        await db.commit()
    else:
        existing = (await db.execute(select(Account.id).limit(1))).scalar_one_or_none()
        if existing is not None:
            return {"seeded": False, "message": "Demo dataset already present."}

    now = utcnow()
    demo_pw_hash = hash_password("DemoPassword123!")
    db.add_all(
        [
            User(
                email="manager@acme-sdr.local",
                full_name="Morgan Hayes",
                role="sales_manager",
                password_hash=demo_pw_hash,
                active=True,
            ),
            User(
                email="sdr@acme-sdr.local",
                full_name="Taylor Brooks",
                role="sdr",
                password_hash=demo_pw_hash,
                active=True,
            ),
            User(
                email="viewer@acme-sdr.local",
                full_name="Casey Reed",
                role="viewer",
                password_hash=demo_pw_hash,
                active=True,
            ),
        ]
    )
    await db.flush()

    helios = Account(
        name="Helios Cloud Systems",
        domain="helioscloud.io",
        industry="Cloud Infrastructure",
        employee_count=340,
        annual_revenue_usd=Decimal("48000000.00"),
        headquarters="Austin, TX",
        tech_stack_json=["Salesforce", "Snowflake", "Kubernetes", "AWS"],
        research_summary=(
            "Series B cloud observability leader expanding enterprise outbound across "
            "North America after hiring new RevOps leadership."
        ),
        status="active",
    )
    vanguard = Account(
        name="Vanguard MedTech",
        domain="vanguardmed.io",
        industry="HealthTech",
        employee_count=180,
        annual_revenue_usd=Decimal("24000000.00"),
        headquarters="Boston, MA",
        tech_stack_json=["HubSpot", "AWS", "Okta"],
        research_summary=(
            "Clinical workflow SaaS prioritizing HIPAA/PII-safe local AI tooling for "
            "commercial SDRs."
        ),
        status="active",
    )
    northstar = Account(
        name="Northstar FreightTech",
        domain="northstarfreight.com",
        industry="Logistics",
        employee_count=620,
        annual_revenue_usd=Decimal("92000000.00"),
        headquarters="Chicago, IL",
        tech_stack_json=["Salesforce", "Databricks", "Slack"],
        research_summary=(
            "Freight automation platform consolidating regional CRM instances and outbound tooling."
        ),
        status="active",
    )
    apex_rival = Account(
        name="Apex Rival Labs",
        domain="apexrival.io",
        industry="Enterprise Software",
        employee_count=290,
        annual_revenue_usd=Decimal("35000000.00"),
        headquarters="San Francisco, CA",
        tech_stack_json=["HubSpot", "AWS"],
        research_summary="Direct competitor — permanently suppressed from outbound prospecting.",
        status="suppressed",
    )
    db.add_all([helios, vanguard, northstar, apex_rival])
    await db.flush()

    signals = [
        AccountSignal(
            account_id=helios.id,
            signal_type="funding",
            title="Closed $42M Series B to scale enterprise GTM",
            summary=(
                "Funding press release highlights doubling SDR headcount and RevOps automation."
            ),
            evidence_excerpt="We are doubling our outbound and enterprise GTM team in Q1-Q2.",
            source_url="https://news.helioscloud.io/series-b",
            confidence=0.95,
            weight=30,
            observed_at=now - timedelta(days=4),
            verified=True,
        ),
        AccountSignal(
            account_id=helios.id,
            signal_type="hiring",
            title="Hiring 6 Enterprise SDRs and Senior RevOps Systems Lead",
            summary=(
                "Job postings specify Salesforce hygiene and multi-touch outbound orchestration."
            ),
            evidence_excerpt="Lead CRM deduplication, ICP scoring, and compliant outbound.",
            source_url="https://jobs.helioscloud.io/revops-lead",
            confidence=0.90,
            weight=25,
            observed_at=now - timedelta(days=2),
            verified=True,
        ),
        AccountSignal(
            account_id=helios.id,
            signal_type="tech_migration",
            title="Migrating analytics warehouse to Snowflake",
            summary="Engineering blog confirms Snowflake rollout for GTM telemetry.",
            evidence_excerpt="Centralizing product usage signals in Snowflake for revenue teams.",
            source_url="https://engineering.helioscloud.io/snowflake",
            confidence=0.88,
            weight=20,
            observed_at=now - timedelta(days=7),
            verified=True,
        ),
        AccountSignal(
            account_id=vanguard.id,
            signal_type="compliance",
            title="Published AI Governance & PII Redaction Initiative",
            summary=(
                "Requires zero-PII cloud fallback or self-hosted Ollama inference for sales AI."
            ),
            evidence_excerpt="All vendor AI workflows must scrub PII prior to external calls.",
            source_url="https://vanguardmed.io/trust",
            confidence=0.92,
            weight=28,
            observed_at=now - timedelta(days=3),
            verified=True,
        ),
        AccountSignal(
            account_id=vanguard.id,
            signal_type="expansion",
            title="Launched hospital network commercial expansion",
            summary="New VP Commercial appointed to accelerate mid-market provider outreach.",
            evidence_excerpt="Expanding outbound coverage across 120 regional health systems.",
            source_url="https://vanguardmed.io/news/expansion",
            confidence=0.86,
            weight=22,
            observed_at=now - timedelta(days=5),
            verified=True,
        ),
        AccountSignal(
            account_id=northstar.id,
            signal_type="intent_surge",
            title="Evaluating CRM pipeline hygiene and dedupe tools",
            summary=(
                "Public RFP notes duplicate contact records across two acquired freight brands."
            ),
            evidence_excerpt="Consolidating 18,000 duplicate contacts and enforcing stage SLA.",
            source_url="https://northstarfreight.com/rfp-revops",
            confidence=0.84,
            weight=24,
            observed_at=now - timedelta(days=6),
            verified=True,
        ),
        AccountSignal(
            account_id=apex_rival.id,
            signal_type="competitor_notice",
            title="Competitor exclusion verified",
            summary="Domain added to global suppression list.",
            evidence_excerpt="Excluded under competitive outbound compliance policy.",
            source_url="https://internal.compliance/suppression",
            confidence=1.0,
            weight=10,
            observed_at=now - timedelta(days=10),
            verified=True,
        ),
    ]
    db.add_all(signals)
    await db.flush()

    for acc in (helios, vanguard, northstar, apex_rival):
        acc_sigs = [s for s in signals if s.account_id == acc.id]
        sig_score, icp_score = compute_account_scores(acc, acc_sigs)
        acc.signal_score = sig_score
        acc.icp_fit_score = icp_score

    elena_primary = Contact(
        account_id=helios.id,
        first_name="Elena",
        last_name="Rostova",
        email="elena.rostova@helioscloud.io",
        title="VP of Revenue Operations",
        seniority="vp",
        department="Revenue Operations",
        phone="+1-512-555-0142",
        crm_external_id="sf-9001",
    )
    elena_dup = Contact(
        account_id=helios.id,
        first_name="Elena",
        last_name="Rostova",
        email="elena.r@helioscloud.io",
        title="VP Revenue Operations",
        seniority="vp",
        department="RevOps",
        phone="+1-512-555-0142",
    )
    marcus_optout = Contact(
        account_id=helios.id,
        first_name="Marcus",
        last_name="Vance",
        email="marcus.vance@helioscloud.io",
        title="Director of Sales Engineering",
        seniority="director",
        department="Sales Engineering",
        phone="+1-512-555-0199",
        do_not_contact=True,
        opt_out_reason="Requested email opt-out during prior webinar follow-up",
        status="suppressed",
    )
    priya = Contact(
        account_id=vanguard.id,
        first_name="Priya",
        last_name="Nair",
        email="priya.nair@vanguardmed.io",
        title="Chief Revenue Officer",
        seniority="c_level",
        department="Executive",
        phone="+1-617-555-0188",
        crm_external_id="hs-4410",
    )
    devon = Contact(
        account_id=northstar.id,
        first_name="Devon",
        last_name="Brooks",
        email="devon.brooks@northstarfreight.com",
        title="Head of Growth Operations",
        seniority="director",
        department="Growth",
        phone="+1-312-555-0124",
    )
    jordan_rival = Contact(
        account_id=apex_rival.id,
        first_name="Jordan",
        last_name="Cole",
        email="jordan.cole@apexrival.io",
        title="VP Sales",
        seniority="vp",
        department="Sales",
        do_not_contact=True,
        opt_out_reason="Competitor domain suppression",
        status="suppressed",
    )
    db.add_all([elena_primary, elena_dup, marcus_optout, priya, devon, jordan_rival])

    sup_email = SuppressionEntry(
        scope="email",
        value="marcus.vance@helioscloud.io",
        reason="Requested email opt-out during prior webinar follow-up",
        source="inbound_reply",
        active=True,
        created_by=actor.email,
    )
    sup_domain = SuppressionEntry(
        scope="domain",
        value="apexrival.io",
        reason="Direct competitor exclusion policy",
        source="compliance_blocklist",
        active=True,
        created_by=actor.email,
    )
    db.add_all([sup_email, sup_domain])
    await db.commit()

    emb_service = EmbeddingService(settings)
    await index_knowledge_chunk(
        db,
        account_id=None,
        source_type="case_study",
        source_ref_id=None,
        title="Series B Cloud Observability Case Study — 38% SQL Lift",
        content=(
            "Automated RevOps signal enrichment and human-approved multi-touch outbound "
            "increased enterprise SQL conversion by 38% while enforcing zero-PII cloud fallback."
        ),
        source_url="https://acme-sdr.local/case-studies/cloud-observability",
        embedding_service=emb_service,
        actor=actor,
        commit=False,
    )
    await index_knowledge_chunk(
        db,
        account_id=None,
        source_type="playbook",
        source_ref_id=None,
        title="HealthTech HIPAA & Local Ollama Deployment Playbook",
        content=(
            "Deploy self-hosted Ollama inference with strict outbound PII scrubbing, "
            "unsubscribe compliance footers, and manager approval queues."
        ),
        source_url="https://acme-sdr.local/playbooks/healthtech-pii",
        embedding_service=emb_service,
        actor=actor,
        commit=False,
    )
    for sig in signals:
        await index_knowledge_chunk(
            db,
            account_id=sig.account_id,
            source_type="signal",
            source_ref_id=sig.id,
            title=sig.title,
            content=sig.evidence_excerpt or sig.summary,
            source_url=sig.source_url,
            embedding_service=emb_service,
            actor=actor,
            commit=False,
        )
    await db.commit()

    await evaluate_lead(
        db,
        account_id=helios.id,
        contact_id=elena_primary.id,
        discovery_notes=(
            "Series B budget allocated for Q2 RevOps automation; manual outbound bottleneck "
            "blocking 35% SQL pipeline target."
        ),
        rubric_weights=None,
        llm_router=llm_router,
        actor=actor,
    )
    await evaluate_lead(
        db,
        account_id=vanguard.id,
        contact_id=priya.id,
        discovery_notes=(
            "Requires self-hosted AI SDR with PII redaction for cloud fallback before Q3 pilot."
        ),
        rubric_weights=None,
        llm_router=llm_router,
        actor=actor,
    )

    await generate_sequence(
        db,
        account_id=helios.id,
        contact_id=elena_primary.id,
        name="Helios Q2 RevOps Automation Sequence",
        channel="email",
        goal="Schedule a 15-minute discovery workflow review",
        num_steps=3,
        llm_router=llm_router,
        actor=actor,
    )

    deal_helios = CrmDeal(
        external_id="sf-opp-101",
        account_id=helios.id,
        primary_contact_id=elena_primary.id,
        name="Helios Cloud — Enterprise AI SDR Pilot",
        stage="proposal",
        amount_usd=Decimal("64000.00"),
        close_date=date.today() + timedelta(days=28),
        owner_email="manager@acme-sdr.local",
        next_step="Deliver security architecture brief and confirm 2-week pilot scope.",
        last_activity_at=now - timedelta(days=2),
    )
    deal_vanguard = CrmDeal(
        external_id="hs-opp-202",
        account_id=vanguard.id,
        primary_contact_id=priya.id,
        name="Vanguard MedTech — HIPAA-Safe Outbound Rollout",
        stage="qualification",
        amount_usd=Decimal("42000.00"),
        close_date=date.today() + timedelta(days=45),
        owner_email="manager@acme-sdr.local",
        next_step="Review Ollama deployment sizing and PII redaction audit log with InfoSec.",
        last_activity_at=now - timedelta(days=4),
    )
    deal_northstar_stale = CrmDeal(
        external_id="sf-opp-303",
        account_id=northstar.id,
        primary_contact_id=devon.id,
        name="Northstar FreightTech — CRM Hygiene Suite",
        stage="negotiation",
        amount_usd=Decimal("85000.00"),
        close_date=date.today() - timedelta(days=5),
        owner_email="sdr@acme-sdr.local",
        next_step="",
        last_activity_at=now - timedelta(days=22),
    )
    for d in (deal_helios, deal_vanguard, deal_northstar_stale):
        await validate_deal_hygiene(db, d)
    db.add_all([deal_helios, deal_vanguard, deal_northstar_stale])
    await db.commit()

    await scan_duplicate_contacts(db, actor=actor)

    sample_payload = {
        "event_id": "seed-hubspot-evt-001",
        "event_type": "deal.upsert",
        "data": {"external_id": "hs-opp-202", "stage": "qualification"},
    }
    sample_hash = hashlib.sha256(
        json.dumps(sample_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    webhook_ev = CrmWebhookEvent(
        idempotency_key="seed-hubspot-evt-001",
        source="hubspot",
        event_type="deal.upsert",
        payload_hash=sample_hash,
        payload_json=sample_payload,
        status="processed",
        result_summary="Deal synced: Vanguard MedTech — HIPAA-Safe Outbound Rollout",
        received_at=now - timedelta(hours=3),
        processed_at=now - timedelta(hours=3),
    )
    db.add(webhook_ev)
    await db.flush()

    await ingest_inbound_reply(
        db,
        sender_email=priya.email,
        subject="Re: HIPAA-safe outbound workflow",
        body="Interested in comparing notes — please send times for a quick demo next Tuesday.",
        sequence_id=None,
        touch_id=None,
        actor=actor,
    )
    await push_crm_sync(
        db,
        operation="deal_next_step_sync",
        entity_id=deal_helios.id,
        settings=settings,
        actor=actor,
    )
    await dispatch_background_job(
        db,
        job_type="crm_hygiene_sweep",
        settings=settings,
        actor=actor,
    )

    await record_audit_event(
        db,
        event_type="seed.demo_loaded",
        actor=actor,
        entity_type="workspace",
        entity_id="ai-sdr-demo",
        action="seeded",
        details={
            "accounts": 4,
            "contacts": 6,
            "signals": len(signals),
            "deals": 3,
        },
    )
    await db.commit()
    return {
        "seeded": True,
        "message": (
            "Loaded demo dataset (4 accounts, 7 signals, 6 contacts, 3-touch sequence, 3 deals)."
        ),
    }
