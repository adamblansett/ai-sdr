import asyncio
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.core.config import Settings, get_settings
from app.crm_sync.hygiene import validate_all_deals
from app.db.base import as_utc, utcnow
from app.db.models import BackgroundJob, SequenceTouch
from app.db.session import build_engine, build_session_factory, init_db
from app.workers.celery_app import celery_app
from app.workers.schemas import BackgroundJobOut

VALID_JOB_TYPES = {"crm_hygiene_sweep", "sequence_followup_sweep"}


def job_to_out(job: BackgroundJob) -> BackgroundJobOut:
    """Serialize a BackgroundJob ORM row."""
    return BackgroundJobOut(
        id=job.id,
        job_type=job.job_type,
        execution_mode=job.execution_mode,
        status=job.status,
        celery_task_id=job.celery_task_id,
        result_json=dict(job.result_json or {}),
        error_message=job.error_message,
        requested_by=job.requested_by,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


async def run_crm_hygiene_sweep(db: AsyncSession, actor: Actor) -> dict[str, Any]:
    """Execute pipeline-wide hygiene validation."""
    res = await validate_all_deals(db, actor=actor, commit=False)
    return {
        "deals_checked": res.deals_checked,
        "deals_flagged": res.deals_flagged,
        "avg_hygiene_score": res.avg_hygiene_score,
    }


async def run_sequence_followup_sweep(db: AsyncSession, actor: Actor) -> dict[str, Any]:
    """Inspect approved/pending follow-up touches respecting HITL and delay schedules."""
    _ = actor
    now = utcnow()
    touches = list((await db.execute(select(SequenceTouch))).scalars().all())
    due_approved = 0
    scheduled_future = 0
    awaiting_approval = 0
    for touch in touches:
        if touch.status == "pending_approval":
            awaiting_approval += 1
        elif touch.status == "approved":
            if touch.scheduled_for is None or as_utc(touch.scheduled_for) <= now:
                due_approved += 1
            else:
                scheduled_future += 1
    return {
        "touches_due_for_dispatch": due_approved,
        "touches_scheduled_future": scheduled_future,
        "touches_awaiting_approval": awaiting_approval,
    }


async def _execute_job_body(db: AsyncSession, job_type: str, actor: Actor) -> dict[str, Any]:
    if job_type == "crm_hygiene_sweep":
        return await run_crm_hygiene_sweep(db, actor)
    if job_type == "sequence_followup_sweep":
        return await run_sequence_followup_sweep(db, actor)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported job_type '{job_type}'.",
    )


async def dispatch_background_job(
    db: AsyncSession,
    *,
    job_type: str,
    settings: Settings,
    actor: Actor,
) -> BackgroundJob:
    """Run a background sweep inline or dispatch via Celery depending on configuration."""
    clean_type = job_type.strip().lower()
    if clean_type not in VALID_JOB_TYPES:
        allowed = ", ".join(sorted(VALID_JOB_TYPES))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid job type '{job_type}'. Expected one of: {allowed}.",
        )

    mode = settings.task_execution_mode
    job = BackgroundJob(
        job_type=clean_type,
        execution_mode=mode,
        status="queued",
        result_json={},
        requested_by=actor.email,
    )
    db.add(job)
    await db.flush()

    if mode == "inline":
        try:
            result = await _execute_job_body(db, clean_type, actor)
            job.status = "completed"
            job.result_json = result
            job.completed_at = utcnow()
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = utcnow()
            raise
    else:
        async_res = execute_celery_job.delay(clean_type, job.id)
        job.celery_task_id = str(getattr(async_res, "id", "")) or None
        job.status = "queued"

    await record_audit_event(
        db,
        event_type="workers.job_dispatched",
        actor=actor,
        entity_type="background_job",
        entity_id=job.id,
        action=job.status,
        details={"job_type": clean_type, "execution_mode": mode},
    )
    await db.commit()
    await db.refresh(job)
    return job


async def _run_celery_job_async(job_type: str, job_id: str) -> dict[str, Any]:
    cfg = get_settings()
    engine = build_engine(cfg.database_url, cfg)
    try:
        await init_db(engine)
        session_factory = build_session_factory(engine)
        async with session_factory() as session:
            actor = Actor(
                email="celery-worker@acme-sdr.local",
                role="admin",
                auth_method="celery_worker",
            )
            result = await _execute_job_body(session, job_type, actor)
            job = await session.get(BackgroundJob, job_id)
            if job is not None:
                job.status = "completed"
                job.result_json = result
                job.completed_at = utcnow()
            await session.commit()
            return result
    finally:
        await engine.dispose()


@celery_app.task(name="ai_sdr.run_job")
def execute_celery_job(job_type: str, job_id: str = "") -> dict[str, Any]:
    """Celery task entrypoint executing background SDR sweeps."""
    return asyncio.run(_run_celery_job_async(job_type, job_id))
