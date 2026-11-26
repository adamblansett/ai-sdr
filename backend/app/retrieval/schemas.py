from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeChunkCreateIn(BaseModel):
    """Payload to index a playbook, case study, signal, or account note."""

    account_id: str | None = None
    source_type: Literal["case_study", "playbook", "signal", "note"] = "case_study"
    title: str = Field(..., min_length=2, max_length=240)
    content: str = Field(..., min_length=4, max_length=10000)
    source_url: str = Field(default="", max_length=500)


class KnowledgeChunkOut(BaseModel):
    """Serialized indexed knowledge chunk."""

    id: str
    account_id: str | None
    source_type: str
    source_ref_id: str | None
    title: str
    content: str
    source_url: str
    embedding_dim: int
    created_by: str
    created_at: datetime


class KnowledgeSearchIn(BaseModel):
    """Semantic similarity search request."""

    query: str = Field(..., min_length=2, max_length=2000)
    account_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.05, ge=0.0, le=1.0)


class KnowledgeSearchHitOut(BaseModel):
    """Ranked semantic knowledge match with cosine similarity score."""

    chunk: KnowledgeChunkOut
    score: float
