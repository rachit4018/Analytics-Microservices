"""Event ingestion service — MICRO-2.1 T1.

The endpoint stays thin; this module does the work. Keeping DB logic out of
the route handler makes it unit-testable and reusable.

Tests: pytest tests/test_ingestion.py -v
"""

from datetime import datetime, timezone
from typing import List

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import Event, IngestionBatch
from src.models.schemas import BatchReceipt, EventCreate

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def ingest_events(
    session: AsyncSession,
    events: List[EventCreate],
    request_id: str,
) -> BatchReceipt:
    """Persist a batch of validated events atomically, with an audit row.

    TODO(dev) T1:
      1. open a batch row:
           batch = IngestionBatch(
               request_id=request_id,
               event_count=len(events),
               started_at=datetime.now(timezone.utc),
           )
           session.add(batch); await session.flush()   # get batch.id
      2. bulk insert the events in ONE statement:
           rows = [e.model_dump() for e in events]
           await session.execute(insert(Event), rows)
         (NOT a loop of session.add — that's the slow path you benchmarked)
      3. close the batch row:
           batch.completed_at = datetime.now(timezone.utc)
           batch.failed_count = 0            # all-or-nothing v1
      4. await session.commit()
      5. return BatchReceipt(
             batch_id=batch.id, request_id=request_id,
             accepted=len(events), rejected=0,
         )

    Think about: why flush() before the bulk insert but commit() only once at
    the end? (Answer in your PR — it's about transaction boundaries.)

    Note: the get_db dependency already rolls back on exception, so if the
    insert raises, the batch row is rolled back too — atomic by construction.
    You do NOT need a try/except here; let it propagate.
    """
    # TODO(dev): implement
    batch = IngestionBatch(
        request_id=request_id,
        event_count=len(events),
        started_at=datetime.now(timezone.utc),
    )
    session.add(batch)
    await session.flush()

    rows = [e.model_dump() for e in events]
    await session.execute(insert(Event), rows)
    batch.completed_at = datetime.now(timezone.utc)
    batch.failed_count = 0
    await session.commit()
    return BatchReceipt(
        batch_id=batch.id, request_id=request_id, accepted=len(events), rejected=0
    )
