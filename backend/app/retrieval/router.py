from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles
from app.db.models import KnowledgeChunk
from app.db.session import get_db
from app.retrieval.embeddings import EmbeddingService, get_embedding_service
from app.retrieval.schemas import (
    KnowledgeChunkCreateIn,
    KnowledgeChunkOut,
    KnowledgeSearchHitOut,
    KnowledgeSearchIn,
)
from app.retrieval.service import chunk_to_out, index_knowledge_chunk, search_knowledge

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.get("/documents", response_model=list[KnowledgeChunkOut])
async def list_knowledge_documents(
    account_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeChunkOut]:
    """List indexed knowledge chunks (case studies, playbooks, signals)."""
    _ = actor
    stmt = select(KnowledgeChunk).order_by(KnowledgeChunk.created_at.desc())
    if account_id:
        stmt = stmt.where(KnowledgeChunk.account_id == account_id)
    if source_type:
        stmt = stmt.where(KnowledgeChunk.source_type == source_type.strip().lower())
    chunks = list((await db.execute(stmt)).scalars().all())
    return [chunk_to_out(c) for c in chunks]


@router.post(
    "/documents",
    response_model=KnowledgeChunkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_document(
    body: KnowledgeChunkCreateIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
) -> KnowledgeChunkOut:
    """Index a playbook, case study, or note with dense vector embeddings."""
    chunk = await index_knowledge_chunk(
        db,
        account_id=body.account_id,
        source_type=body.source_type,
        source_ref_id=None,
        title=body.title,
        content=body.content,
        source_url=body.source_url,
        embedding_service=embedding_service,
        actor=actor,
    )
    return chunk_to_out(chunk)


@router.post("/search", response_model=list[KnowledgeSearchHitOut])
async def search_knowledge_endpoint(
    body: KnowledgeSearchIn,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
) -> list[KnowledgeSearchHitOut]:
    """Search indexed evidence and case studies using cosine similarity."""
    _ = actor
    return await search_knowledge(
        db,
        query=body.query,
        account_id=body.account_id,
        top_k=body.top_k,
        min_score=body.min_score,
        embedding_service=embedding_service,
    )
