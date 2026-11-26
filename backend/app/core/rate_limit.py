import json
import time
from collections import defaultdict, deque
from threading import Lock

import redis.asyncio as aioredis
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.telemetry import MetricsRegistry

_EXEMPT_PREFIXES = (
    "/api/v1/health",
    "/api/v1/metrics",
)


class RateLimitMiddleware:
    """Pure ASGI sliding-window rate limiter backed by Redis or in-memory fallback."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self._lock = Lock()
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._redis_client: aioredis.Redis | None = None
        if settings.redis_url.strip():
            self._redis_client = aioredis.from_url(
                settings.redis_url.strip(),
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )

    def _client_key(self, scope: Scope) -> str:
        for key, value in scope.get("headers") or []:
            if key.decode("latin-1").lower() == "x-forwarded-for":
                first = value.decode("latin-1", errors="ignore").split(",")[0].strip()
                if first:
                    return first
        client = scope.get("client")
        if isinstance(client, tuple | list) and client:
            return str(client[0])
        return "local"

    async def _check_limit(self, client_key: str, limit: int) -> tuple[bool, int, int]:
        now = time.time()
        window_seconds = 60

        if self._redis_client is not None:
            try:
                bucket = int(now // window_seconds)
                redis_key = f"ai_sdr:rl:{client_key}:{bucket}"
                count = await self._redis_client.incr(redis_key)
                if count == 1:
                    await self._redis_client.expire(redis_key, window_seconds)
                remaining = max(0, limit - int(count))
                retry_after = max(1, window_seconds - int(now % window_seconds))
                return int(count) <= limit, remaining, retry_after
            except Exception:
                # Fall back seamlessly to local window if Redis is unavailable.
                pass

        with self._lock:
            dq = self._windows[client_key]
            cutoff = now - window_seconds
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry_after = max(1, int(window_seconds - (now - dq[0])))
                return False, 0, retry_after
            dq.append(now)
            return True, max(0, limit - len(dq)), 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        limit = max(1, self.settings.rate_limit_requests_per_minute)
        client_key = self._client_key(scope)
        allowed, remaining, retry_after = await self._check_limit(client_key, limit)

        if not allowed:
            app_obj = scope.get("app")
            metrics = getattr(getattr(app_obj, "state", None), "metrics", None)
            if isinstance(metrics, MetricsRegistry):
                metrics.inc("rate_limit_blocked_total")

            body = json.dumps(
                {
                    "detail": "Rate limit exceeded. Retry shortly.",
                    "retry_after_seconds": retry_after,
                }
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(retry_after).encode("latin-1")),
                        (b"x-ratelimit-limit", str(limit).encode("latin-1")),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-ratelimit-limit", str(limit).encode("latin-1")))
                headers.append((b"x-ratelimit-remaining", str(remaining).encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
