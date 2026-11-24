from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SequenceGenerateIn(BaseModel):
    """Payload to generate a grounded multi-touch outbound sequence."""

    account_id: str
    contact_id: str
    name: str = Field(default="", max_length=200)
    channel: Literal["email", "linkedin", "multi_channel"] = "email"
    goal: str = Field(
        default="Schedule a 15-minute discovery workflow review",
        min_length=3,
        max_length=300,
    )
    num_steps: int = Field(default=3, ge=1, le=5)


class TouchUpdateIn(BaseModel):
    """Payload to edit an outbound touch draft before sending."""

    subject: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=10000)


class SequenceTouchOut(BaseModel):
    """Serialized individual touch in an outbound sequence."""

    id: str
    sequence_id: str
    step_number: int
    delay_days: int
    channel: str
    subject: str
    body: str
    unsubscribe_footer_included: bool
    cited_signal_ids: list[str]
    grounded_facts: list[str]
    status: str
    approval_id: str | None
    llm_provider: str
    llm_model: str
    pii_redacted: bool
    approved_by: str | None
    approved_at: datetime | None
    sent_at: datetime | None
    provider_message_id: str | None
    created_at: datetime


class SequenceOut(BaseModel):
    """Serialized multi-touch sequence with child touches."""

    id: str
    name: str
    account_id: str
    contact_id: str
    channel: str
    goal: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    touches: list[SequenceTouchOut]
