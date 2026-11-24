from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RubricWeightsIn(BaseModel):
    """Customizable ICP rubric dimension weights."""

    company_size: int = Field(default=20, ge=0, le=100)
    industry_fit: int = Field(default=20, ge=0, le=100)
    tech_stack_fit: int = Field(default=15, ge=0, le=100)
    buying_signals: int = Field(default=30, ge=0, le=100)
    buyer_authority: int = Field(default=15, ge=0, le=100)


class EvaluateLeadIn(BaseModel):
    """Payload requesting ICP scoring and BANT/MEDDIC qualification."""

    account_id: str
    contact_id: str | None = None
    discovery_notes: str = Field(default="", max_length=6000)
    rubric_weights: RubricWeightsIn | None = None


class RubricDimensionOut(BaseModel):
    """Single scored dimension in the ICP qualification rubric."""

    dimension: str
    weight: int
    score: int
    max_score: int
    reason: str


class EvidenceCitationOut(BaseModel):
    """Verified public signal cited during qualification."""

    signal_id: str
    signal_type: str
    title: str
    source_url: str
    excerpt: str
    confidence: float


class QualificationOut(BaseModel):
    """Serialized qualification assessment with BANT, MEDDIC, and citations."""

    id: str
    account_id: str
    contact_id: str | None
    icp_score: int
    intent_tier: str
    grade: str
    bant: dict[str, Any]
    meddic: dict[str, Any]
    rubric_breakdown: list[RubricDimensionOut]
    evidence_citations: list[EvidenceCitationOut]
    rationale: str
    llm_provider: str
    llm_model: str
    pii_redacted: bool
    created_by: str
    created_at: datetime
