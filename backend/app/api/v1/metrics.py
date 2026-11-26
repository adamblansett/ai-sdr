from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from app.core.auth import Actor, get_current_actor
from app.core.telemetry import MetricsRegistry

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _get_registry(request: Request) -> MetricsRegistry:
    registry = getattr(request.app.state, "metrics", None)
    if isinstance(registry, MetricsRegistry):
        return registry
    return MetricsRegistry()


@router.get("", response_model=dict[str, int])
async def get_metrics(
    request: Request,
    actor: Actor = Depends(get_current_actor),
) -> dict[str, int]:
    """Return operational request, LLM, delivery, and worker counters."""
    _ = actor
    return _get_registry(request).snapshot()


@router.get("/prometheus", response_class=PlainTextResponse)
async def get_prometheus_metrics(request: Request) -> PlainTextResponse:
    """Expose Prometheus text-format counters for scraping."""
    return PlainTextResponse(
        content=_get_registry(request).render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
