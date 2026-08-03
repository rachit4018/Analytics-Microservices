"""Pytest configuration — shared fixtures and collection rules.

This file is YOURS to edit (unlike tests/test_schema.py).

It solves three problems:
  1. .env is not read automatically by Python — we load it here, before
     any test module is imported, so os.environ.get(...) in the test file
     sees the right database URLs.
  2. Tests need a migrated + seeded database. We bootstrap it once per run
     instead of relying on you having run the right commands by hand.
  3. Destructive migration tests (downgrade/upgrade) wipe the seeded data
     that other tests depend on. We force them to run LAST.
"""

import os
import sys
import subprocess

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import pytest_asyncio
from src.models.session import AsyncSessionLocal

# Loaded at import time — before test modules are collected.
# override=False means a variable already exported in your shell wins.
# If your shell has a stale DATABASE_URL, that is what will be used.
load_dotenv(override=False)

REQUIRED_ROWS = 100_000


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL_SYNC")
    if not url:
        raise RuntimeError(
            "DATABASE_URL_SYNC is not set. Add it to .env with an EXPLICIT "
            "host and port, e.g. "
            "postgresql+psycopg2://analytics:analytics@127.0.0.1:5432/analytics"
        )
    return url


@pytest.fixture(scope="session")
def engine():
    """Sync engine for inspection queries.

    Note: if tests/test_schema.py defines its own `engine` fixture, that one
    wins — fixtures in a test module shadow conftest fixtures of the same
    name. This is here as a fallback.
    """
    eng = create_engine(_sync_url())
    yield eng
    eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def bootstrap_database():
    """Guarantee schema + data exist before any test runs.

    Runs once per pytest session. Idempotent: skips seeding when the table
    already has enough rows, so repeat runs stay fast.
    """
    subprocess.run(["alembic", "upgrade", "head"], check=True)

    eng = create_engine(_sync_url())
    with eng.connect() as conn:
        db_name = conn.execute(text("SELECT current_database()")).scalar()
        port = conn.execute(text("SELECT inet_server_port()")).scalar()
        count = conn.execute(text("SELECT count(*) FROM events")).scalar()

    print(f"\n[bootstrap] db={db_name} port={port} rows={count}")

    if count < REQUIRED_ROWS:
        print(f"[bootstrap] seeding (found {count}, need {REQUIRED_ROWS})...")
        subprocess.run([sys.executable, "-m", "scripts.seed_events"], check=True)
        with eng.connect() as conn:
            conn.execute(text("ANALYZE events"))
            conn.commit()

        with eng.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM events")).scalar()

        print(f"[bootstrap] rows after seed: {count}")

    eng.dispose()
    yield


def pytest_collection_modifyitems(items):
    """Order tests so destructive ones run last.

    Priority (lower runs first):
      0 = normal tests (ORM, schemas, session, seed, query plans) — need the
          seeded 100k rows intact
      1 = migration/downgrade tests — drop and recreate the schema
      2 = ingestion tests — write to events/ingestion_batches and are
          truncated by the isolate fixture
    """

    def priority(item) -> int:
        name = item.name.lower()
        nodeid = item.nodeid.lower()
        if "test_ingestion" in nodeid:
            return 2
        if any(m in name for m in ("downgrade", "migration")):
            return 1
        return 0

    items.sort(key=priority)


@pytest_asyncio.fixture(autouse=True)
async def isolate_ingestion_tests(request):
    """Truncate write tables ONLY for ingestion tests.

    Seed-dependent tests (test_schema.py) keep their 100k rows because this
    fixture no-ops for them. One pytest invocation, correct isolation for both.
    """
    if "test_ingestion" not in request.node.nodeid:
        yield
        return

    async with AsyncSessionLocal() as s:
        await s.execute(
            text("TRUNCATE events, ingestion_batches RESTART IDENTITY CASCADE")
        )
        await s.commit()
    yield
