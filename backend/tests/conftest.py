from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

MANAGER_HEADERS = {
    "X-Actor-Email": "manager@test.local",
    "X-Actor-Role": "sales_manager",
}
SDR_HEADERS = {
    "X-Actor-Email": "sdr@test.local",
    "X-Actor-Role": "sdr",
}
VIEWER_HEADERS = {
    "X-Actor-Email": "viewer@test.local",
    "X-Actor-Role": "viewer",
}


def make_test_app(tmp_path: Path, **overrides: Any) -> FastAPI:
    """Create an isolated FastAPI app backed by a per-test SQLite file."""
    db_file = tmp_path / "test_ai_sdr.db"
    cfg = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        llm_default_provider="mock",
        auto_create_tables=True,
        seed_demo_data=False,
        **overrides,
    )
    return create_app(cfg)


@asynccontextmanager
async def app_client(
    tmp_path: Path, **overrides: Any
) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    """Yield (app, AsyncClient) and cleanly dispose the DB engine afterwards."""
    test_app = make_test_app(tmp_path, **overrides)
    transport = ASGITransport(app=test_app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield test_app, client
    finally:
        await test_app.state.db_engine.dispose()
