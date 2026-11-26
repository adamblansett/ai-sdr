from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "ai_sdr",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_always_eager=_settings.task_execution_mode == "inline",
    beat_schedule={
        "crm-hygiene-hourly": {
            "task": "ai_sdr.run_job",
            "schedule": 3600.0,
            "args": ["crm_hygiene_sweep"],
        },
        "sequence-followup-15m": {
            "task": "ai_sdr.run_job",
            "schedule": 900.0,
            "args": ["sequence_followup_sweep"],
        },
    },
)
