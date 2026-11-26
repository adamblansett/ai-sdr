from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles
from app.db.models import Account, AccountSignal, Contact, SuppressionEntry
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.prospecting.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountResearchOut,
    ContactCreateIn,
    ContactOut,
    CsvImportIn,
    CsvImportOut,
    SignalCreateIn,
    SignalOut,
    SuppressionApplyOut,
    SuppressionCreateIn,
    SuppressionEntryOut,
)
from app.prospecting.service import (
    account_to_out,
    add_account_signal,
    apply_suppression,
    contact_to_out,
    contacts_to_out,
    create_account,
    create_contact,
    deactivate_suppression,
    import_contacts_csv,
    suppression_to_out,
    synthesize_account_research,
)
from app.retrieval.embeddings import EmbeddingService, get_embedding_service

router = APIRouter(prefix="/prospecting", tags=["prospecting"])


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[AccountOut]:
    """List target accounts sorted by ICP fit score."""
    _ = actor
    accounts = list(
        (
            await db.execute(
                select(Account).order_by(Account.icp_fit_score.desc(), Account.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [account_to_out(acc) for acc in accounts]


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def create_account_endpoint(
    body: AccountCreateIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> AccountOut:
    """Create a target B2B account."""
    account = await create_account(db, payload=body, actor=actor)
    return account_to_out(account)


@router.get("/accounts/{account_id}/signals", response_model=list[SignalOut])
async def list_account_signals(
    account_id: str,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[AccountSignal]:
    """List public buying signals attached to an account."""
    _ = actor
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )
    stmt = (
        select(AccountSignal)
        .where(AccountSignal.account_id == account_id)
        .order_by(AccountSignal.observed_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/accounts/{account_id}/signals",
    response_model=SignalOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_signal_endpoint(
    account_id: str,
    body: SignalCreateIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
) -> AccountSignal:
    """Record a verified public buying signal and refresh account scores."""
    return await add_account_signal(
        db,
        account_id=account_id,
        payload=body,
        actor=actor,
        embedding_service=embedding_service,
    )


@router.post("/accounts/{account_id}/research", response_model=AccountResearchOut)
async def research_account_endpoint(
    account_id: str,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> AccountResearchOut:
    """Synthesize account research brief grounded in verified signals."""
    return await synthesize_account_research(
        db,
        account_id=account_id,
        llm_router=llm_router,
        actor=actor,
    )


@router.get("/contacts", response_model=list[ContactOut])
async def list_contacts(
    include_merged: bool = Query(default=False),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[ContactOut]:
    """List contacts with live email/domain suppression posture."""
    _ = actor
    stmt = select(Contact).order_by(Contact.created_at.desc())
    if not include_merged:
        stmt = stmt.where(Contact.status != "merged")
    contacts = list((await db.execute(stmt)).scalars().all())
    return await contacts_to_out(db, contacts)


@router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact_endpoint(
    body: ContactCreateIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    """Create a prospect contact under a target account."""
    contact = await create_contact(db, payload=body, actor=actor)
    return await contact_to_out(db, contact)


@router.post("/contacts/import-csv", response_model=CsvImportOut)
async def import_contacts_csv_endpoint(
    body: CsvImportIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> CsvImportOut:
    """Bulk import prospect contacts from CSV text."""
    return await import_contacts_csv(db, csv_text=body.csv_text, actor=actor)


@router.get("/suppressions", response_model=list[SuppressionEntryOut])
async def list_suppressions(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[SuppressionEntryOut]:
    """List all email and domain suppression entries."""
    _ = actor
    entries = list(
        (
            await db.execute(
                select(SuppressionEntry).order_by(
                    SuppressionEntry.active.desc(), SuppressionEntry.created_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [suppression_to_out(entry) for entry in entries]


@router.post(
    "/suppressions",
    response_model=SuppressionApplyOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_suppression_endpoint(
    body: SuppressionCreateIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> SuppressionApplyOut:
    """Add an email/domain suppression and immediately block pending outbound touches."""
    entry, contacts_affected, touches_blocked = await apply_suppression(
        db,
        scope=body.scope,
        value=body.value,
        reason=body.reason,
        source=body.source,
        actor=actor,
    )
    return SuppressionApplyOut(
        entry=suppression_to_out(entry),
        contacts_affected=contacts_affected,
        touches_blocked=touches_blocked,
    )


@router.delete("/suppressions/{entry_id}", response_model=SuppressionEntryOut)
async def deactivate_suppression_endpoint(
    entry_id: str,
    actor: Actor = Depends(require_roles("sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> SuppressionEntryOut:
    """Deactivate a suppression entry (sales_manager/admin only)."""
    entry = await deactivate_suppression(db, entry_id=entry_id, actor=actor)
    return suppression_to_out(entry)
