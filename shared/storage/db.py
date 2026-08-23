"""
shared/storage/db.py — Shared async SQLAlchemy engine + session factory (Postgres).

Initialized once at module load, disposed on app shutdown.
Never call create_async_engine() elsewhere — import from here instead.

Unlike Redis/tracing, this is NOT a safe-to-skip integration — a database is
core data, not an optional side effect. DATABASE_URL is a required setting
(see config.py); there's no no-op fallback here.

Usage in FastAPI route handlers (via Depends):
  from shared.storage import DBSession
  @router.get("/example")
  async def example(db: DBSession):
    result = await db.execute(select(SomeModel))

Usage outside a route (e.g. a service):
  from shared.storage import async_session
  async with async_session() as db:
    ...
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
  async with async_session() as session:
    yield session


DBSession = Annotated[AsyncSession, Depends(get_db)]
