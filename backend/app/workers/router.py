from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles, resolve_request_settings
from app.core.telemetry import MetricsRegistry
from app.db.models import BackgroundJob
from app.db.session import get_db
from app.workers.schemas import BackgroundJobOut
from app.workers.tasks import dispatch_background_job, job_to_out

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("/jobs", response_model=list[BackgroundJobOut])
async def list_background_jobs(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[BackgroundJobOut]:
    """List background worker executions."""
    _ = actor
    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(50)
    jobs = list((await db.execute(stmt)).scalars().all())
    return [job_to_out(j) for j in jobs]


@router.post(
    "/jobs/{job_type}/run",
    response_model=BackgroundJobOut,
    status_code=status.HTTP_201_CREATED,
)
async def run_background_job_endpoint(
    job_type: str,
    request: Request,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> BackgroundJobOut:
    """Trigger a background worker job (inline in dev/CI or Celery in production)."""
    cfg = resolve_request_settings(request)
    job = await dispatch_background_job(db, job_type=job_type, settings=cfg, actor=actor)
    metrics = getattr(request.app.state, "metrics", None)
    if isinstance(metrics, MetricsRegistry):
        metrics.inc("background_jobs_total")
    return job_to_out(job)
