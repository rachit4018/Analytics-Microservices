"""Async database engine + session management — MICRO-1.4.

Tests: pytest tests/test_session.py -v

Docs you'll need:
  https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
  (async_sessionmaker, AsyncSession, create_async_engine)

This module is imported by every endpoint that touches the database. Get the
lifecycle right: one engine, pooled connections, a fresh session per request,
rollback on error, always close.
"""

import os
from typing import AsyncGenerator
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/test_db"
)
_TESTING = os.environ.get("TESTING") == "1"
_pool_kwargs = (
    {"poolclass": NullPool} if _TESTING else {"pool_size": 10, "max_overflow": 20}
)

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
    **_pool_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncGenerator:

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
