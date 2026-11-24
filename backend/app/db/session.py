import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base


def build_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine tuned for SQLite or PostgreSQL."""
    kwargs: dict[str, Any] = {"echo": False}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_pre_ping"] = True
    return create_async_engine(database_url, **kwargs)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Create database tables if they do not exist."""
    import app.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_db_ready(engine: AsyncEngine) -> bool:
    """Verify database connectivity with a lightweight SELECT 1 probe."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def ensure_db_initialized(app: FastAPI) -> None:
    """Lazily initialize schema once per app instance if auto_create_tables is enabled."""
    if getattr(app.state, "db_initialized", False):
        return
    settings: Settings = app.state.settings
    if not settings.auto_create_tables:
        app.state.db_initialized = True
        return
    lock: asyncio.Lock = app.state.db_init_lock
    async with lock:
        if not getattr(app.state, "db_initialized", False):
            await init_db(app.state.db_engine)
            app.state.db_initialized = True


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an initialized AsyncSession."""
    await ensure_db_initialized(request.app)
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session
