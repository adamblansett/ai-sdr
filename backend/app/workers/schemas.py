from datetime import datetime
from typing import Any

from pydantic import BaseModel


class BackgroundJobOut(BaseModel):
    """Serialized background worker job execution record."""

    id: str
    job_type: str
    execution_mode: str
    status: str
    celery_task_id: str | None
    result_json: dict[str, Any]
    error_message: str | None
    requested_by: str
    created_at: datetime
    completed_at: datetime | None
