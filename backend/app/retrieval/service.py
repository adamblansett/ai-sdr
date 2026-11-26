from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.db.models import Account, KnowledgeChunk
from app.retrieval.embeddings import EmbeddingService, cosine_similarity
from app.retrieval.schemas import KnowledgeChunkOut, KnowledgeSearchHitOut


def chunk_to_out(chunk: KnowledgeChunk) -> KnowledgeChunkOut:
    """Serialize a KnowledgeChunk ORM row."""
    return KnowledgeChunkOut(
        id=chunk.id,
        account_id=chunk.account_id,
        source_type=chunk.source_type,
        source_ref_id=chunk.source_ref_id,
        title=chunk.title,
        content=chunk.content,
        source_url=chunk.source_url,
        embedding_dim=chunk.embedding_dim,
        created_by=chunk.created_by,
        created_at=chunk.created_at,
    )


async def index_knowledge_chunk(
    db: AsyncSession,
    *,
    account_id: str | None,
    source_type: str,
    source_ref_id: str | None,
    title: str,
    content: str,
    source_url: str,
    embedding_service: EmbeddingService,
    actor: Actor,
    commit: bool = True,
) -> KnowledgeChunk:
    """Embed and store a knowledge chunk for semantic evidence retrieval."""
    if account_id:
        account = await db.get(Account, account_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account '{account_id}' not found.",
            )

    full_text = f"{title.strip()}\n{content.strip()}".strip()
    vector = await embedding_service.embed(full_text)
    chunk = KnowledgeChunk(
        account_id=account_id,
        source_type=source_type.strip().lower(),
        source_ref_id=source_ref_id,
        title=title.strip()[:240],
        content=content.strip(),
        source_url=source_url.strip()[:500],
        embedding_json=vector,
        embedding_dim=len(vector),
        created_by=actor.email,
    )
    db.add(chunk)
    await db.flush()

    await record_audit_event(
        db,
        event_type="retrieval.chunk_indexed",
        actor=actor,
        entity_type="knowledge_chunk",
        entity_id=chunk.id,
        action="indexed",
        details={
            "account_id": account_id,
            "source_type": chunk.source_type,
            "embedding_dim": chunk.embedding_dim,
        },
    )
    if commit:
        await db.commit()
        await db.refresh(chunk)
    return chunk


async def search_knowledge(
    db: AsyncSession,
    *,
    query: str,
    account_id: str | None = None,
    top_k: int = 5,
    min_score: float = 0.05,
    embedding_service: EmbeddingService,
) -> list[KnowledgeSearchHitOut]:
    """Return top-k knowledge chunks ranked by cosine similarity."""
    stmt = select(KnowledgeChunk)
    if account_id:
        stmt = stmt.where(
            or_(KnowledgeChunk.account_id == account_id, KnowledgeChunk.account_id.is_(None))
        )
    chunks = list((await db.execute(stmt)).scalars().all())
    if not chunks:
        return []

    query_vec = await embedding_service.embed(query)
    scored: list[tuple[float, KnowledgeChunk]] = []
    for chunk in chunks:
        score = cosine_similarity(query_vec, list(chunk.embedding_json or []))
        if score >= min_score:
            scored.append((round(score, 4), chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        KnowledgeSearchHitOut(chunk=chunk_to_out(chunk), score=score)
        for score, chunk in scored[:top_k]
    ]
