from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

from opentelemetry import trace

_METRIC_NAMES: tuple[str, ...] = (
    "http_requests_total",
    "http_4xx_total",
    "http_5xx_total",
    "rate_limit_blocked_total",
    "llm_calls_total",
    "touches_sent_total",
    "replies_classified_total",
    "crm_sync_jobs_total",
    "background_jobs_total",
)


class MetricsRegistry:
    """Thread-safe in-memory operational counters exported as JSON and Prometheus text."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = {name: 0 for name in _METRIC_NAMES}

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def render_prometheus(self) -> str:
        lines: list[str] = []
        for name, val in self.snapshot().items():
            metric = f"ai_sdr_{name}"
            lines.append(f"# TYPE {metric} counter")
            lines.append(f"{metric} {val}")
        return "\n".join(lines) + "\n"


@contextmanager
def start_span(
    name: str,
    enabled: bool = False,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Start an OpenTelemetry span when OTEL_ENABLED=true; no-op otherwise."""
    if not enabled:
        yield None
        return
    tracer = trace.get_tracer("ai-sdr")
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, val in attributes.items():
                span.set_attribute(key, val)
        yield span
