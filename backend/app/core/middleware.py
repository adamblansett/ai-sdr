import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.telemetry import MetricsRegistry

logger = structlog.get_logger(__name__)

_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware:
    """Pure ASGI middleware for request IDs, correlation logs, metrics, and security headers."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id: str | None = None
        for key, value in scope.get("headers") or []:
            if key.decode("latin-1").lower() == "x-request-id":
                candidate = value.decode("latin-1", errors="ignore").strip()[:128]
                if candidate:
                    request_id = candidate
                    break
        resolved_id = request_id or str(uuid.uuid4())
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = resolved_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=resolved_id)

        path = str(scope.get("path", ""))
        method = str(scope.get("method", ""))
        started = time.perf_counter()
        status_code = 500
        app_obj = scope.get("app")
        metrics = getattr(getattr(app_obj, "state", None), "metrics", None)

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 200))
                headers = list(message.get("headers") or [])
                existing = {k.lower() for k, _ in headers}

                def _set_header(name: bytes, val: bytes) -> None:
                    if name.lower() not in existing:
                        headers.append((name, val))
                        existing.add(name.lower())

                _set_header(b"x-request-id", resolved_id.encode("latin-1"))
                _set_header(b"x-content-type-options", b"nosniff")
                _set_header(b"x-frame-options", b"DENY")
                _set_header(b"referrer-policy", b"strict-origin-when-cross-origin")
                _set_header(
                    b"permissions-policy",
                    b"camera=(), microphone=(), geolocation=()",
                )
                if not any(path.startswith(p) for p in _DOCS_PATHS):
                    _set_header(
                        b"content-security-policy",
                        b"default-src 'none'; frame-ancestors 'none'",
                    )
                if self.settings.app_env.strip().lower() == "production":
                    _set_header(
                        b"strict-transport-security",
                        b"max-age=31536000; includeSubDomains",
                    )
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if isinstance(metrics, MetricsRegistry):
                metrics.inc("http_requests_total")
                if 400 <= status_code < 500:
                    metrics.inc("http_4xx_total")
                elif status_code >= 500:
                    metrics.inc("http_5xx_total")
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.debug(
                "http_request_completed",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            structlog.contextvars.clear_contextvars()
