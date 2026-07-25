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
            "postgresql+psycopg2://user:pass@localhost:5432/test_db"
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
    """Run destructive migration tests LAST.

    A test that does `alembic downgrade base` drops the events table and
    therefore the 100k seeded rows. If it runs before the seed/index tests,
    those fail with count=0 — which is exactly the order-dependent failure
    you hit when running the full file versus `-k seed`.

    Sorting here is a pragmatic fix. The cleaner long-term answer is to run
    destructive schema tests as a SEPARATE pytest invocation in CI:
        pytest tests/test_schema.py -k "orm or seed"
        pytest tests/test_schema.py -k migration
    """
    destructive_markers = ("downgrade", "migration")

    def is_destructive(item) -> bool:
        return any(marker in item.name.lower() for marker in destructive_markers)

    items.sort(key=is_destructive)
