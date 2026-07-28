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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/test_db"
)


# TODO(dev) T1: create the engine (ONE for the whole app)
#   engine = create_async_engine(
#       DATABASE_URL,
#       pool_size=...,          # steady-state pooled connections (e.g. 10)
#       max_overflow=...,       # burst capacity above pool_size (e.g. 20)
#       pool_pre_ping=True,     # test a connection before handing it out
#       echo=False,
#   )
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

# TODO(dev) T1: create the session factory
#   AsyncSessionLocal = async_sessionmaker(
#       bind=engine,
#       expire_on_commit=False,  # why? see the ticket — matters for async
#       class_=AsyncSession,
#   )

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncGenerator:
    """FastAPI dependency: yield a session, roll back on error, always close.

    TODO(dev) T2:
      async with AsyncSessionLocal() as session:
          try:
              yield session
          except Exception:
              await session.rollback()
              raise          # re-raise so the error handler middleware sees it
          finally:
              await session.close()

    Think about: why rollback on ANY exception? Why re-raise instead of
    swallowing? Why is 'finally: close' needed if 'async with' already closes?
    (Answer the last one in your PR — it's subtle.)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise Exception
        finally:
            await session.close()
