import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles, resolve_request_settings
from app.crm_sync.hygiene import (
    candidate_to_out,
    create_deal,
    deal_to_out,
    process_crm_webhook,
    scan_duplicate_contacts,
    synthesize_deal_next_step,
    validate_all_deals,
    webhook_to_out,
)
from app.crm_sync.schemas import (
    CrmDealCreateIn,
    CrmDealOut,
    CrmWebhookEventOut,
    CrmWebhookPayloadIn,
    DeduplicateOut,
    DuplicateMergeCandidateOut,
    HygieneValidateOut,
)
from app.db.models import CrmDeal, CrmWebhookEvent, DuplicateMergeCandidate
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/crm", tags=["crm_sync"])


@router.get("/deals", response_model=list[CrmDealOut])
async def list_deals(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[CrmDealOut]:
    """List CRM deals sorted by hygiene risk and recency."""
    _ = actor
    deals = list(
        (
            await db.execute(
                select(CrmDeal).order_by(CrmDeal.hygiene_score.asc(), CrmDeal.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [deal_to_out(d) for d in deals]


@router.post("/deals", response_model=CrmDealOut, status_code=status.HTTP_201_CREATED)
async def create_deal_endpoint(
    body: CrmDealCreateIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> CrmDealOut:
    """Create a CRM pipeline deal with initial hygiene validation."""
    deal = await create_deal(db, payload=body, actor=actor)
    return deal_to_out(deal)


@router.post("/deals/{deal_id}/next-step", response_model=CrmDealOut)
async def synthesize_next_step_endpoint(
    deal_id: str,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> CrmDealOut:
    """Synthesize a next-step summary for a CRM deal."""
    deal = await synthesize_deal_next_step(
        db,
        deal_id=deal_id,
        llm_router=llm_router,
        actor=actor,
    )
    return deal_to_out(deal)


@router.post("/hygiene/validate", response_model=HygieneValidateOut)
async def validate_pipeline_hygiene_endpoint(
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> HygieneValidateOut:
    """Re-validate stage hygiene across all CRM deals."""
    return await validate_all_deals(db, actor=actor)


@router.post("/hygiene/deduplicate", response_model=DeduplicateOut)
async def deduplicate_contacts_endpoint(
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> DeduplicateOut:
    """Scan contacts for duplicates and queue HITL merge approvals."""
    created = await scan_duplicate_contacts(db, actor=actor)
    all_candidates = list(
        (
            await db.execute(
                select(DuplicateMergeCandidate).order_by(
                    DuplicateMergeCandidate.created_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    serialized = [await candidate_to_out(db, cand) for cand in all_candidates]
    return DeduplicateOut(candidates_created=len(created), candidates=serialized)


@router.get("/hygiene/duplicates", response_model=list[DuplicateMergeCandidateOut])
async def list_duplicate_candidates(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[DuplicateMergeCandidateOut]:
    """List detected duplicate contact merge candidates."""
    _ = actor
    candidates = list(
        (
            await db.execute(
                select(DuplicateMergeCandidate).order_by(
                    DuplicateMergeCandidate.created_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [await candidate_to_out(db, cand) for cand in candidates]


@router.get("/webhooks", response_model=list[CrmWebhookEventOut])
async def list_webhook_events(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[CrmWebhookEventOut]:
    """List recently processed CRM webhook events."""
    _ = actor
    events = list(
        (
            await db.execute(
                select(CrmWebhookEvent)
                .order_by(CrmWebhookEvent.received_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [webhook_to_out(ev, duplicate_ignored=False) for ev in events]


@router.post("/webhooks/{source}", response_model=CrmWebhookEventOut)
async def ingest_crm_webhook(
    source: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CrmWebhookEventOut:
    """Idempotently ingest a CRM webhook authenticated by HMAC signature or actor role."""
    settings = resolve_request_settings(request)
    raw_body = await request.body()

    sig_header = request.headers.get("x-webhook-signature", "").strip()
    if sig_header:
        provided = sig_header.removeprefix("sha256=").strip().lower()
        expected = hmac.new(
            settings.effective_webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook HMAC signature.",
            )
        actor = Actor(
            email=f"webhook-{source.strip().lower()}@crm-sync.local",
            role="admin",
            auth_method="webhook_hmac",
        )
    else:
        actor = await get_current_actor(request)
        if actor.role not in ("sdr", "sales_manager", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions; required role: sdr, sales_manager, admin.",
            )

    try:
        raw_json = json.loads(raw_body.decode("utf-8"))
        payload = CrmWebhookPayloadIn.model_validate(raw_json)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CRM webhook payload: {exc}",
        ) from exc

    idempotency_key = (
        request.headers.get("idempotency-key", "").strip() or (payload.event_id or "").strip()
    )
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook requires Idempotency-Key header or payload.event_id.",
        )

    event, duplicate_ignored = await process_crm_webhook(
        db,
        source=source,
        idempotency_key=idempotency_key,
        event_type=payload.event_type,
        payload=raw_json,
        actor=actor,
    )
    return webhook_to_out(event, duplicate_ignored=duplicate_ignored)
