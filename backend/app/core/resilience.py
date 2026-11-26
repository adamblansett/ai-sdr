import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx


async def async_retry_with_backoff[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    ),
) -> T:
    """Execute an idempotent async call with capped exponential backoff and jitter."""
    attempts = max(1, max_attempts)
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except retry_on as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = random.uniform(0.0, delay * 0.25)
            await asyncio.sleep(delay + jitter)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("async_retry_with_backoff exited without result")
