"""Event ingestion service — MICRO-2.1 T1.

The endpoint stays thin; this module does the work. Keeping DB logic out of
the route handler makes it unit-testable and reusable.

Tests: pytest tests/test_ingestion.py -v
"""

from datetime import datetime, timezone
from typing import List

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.anomalies import ANOMALIES_CACHE_PREFIX
from src.models.database import Event, IngestionBatch
from src.models.schemas import BatchReceipt, EventCreate
from src.services.cache import cache_delete_pattern


async def ingest_events(
    session: AsyncSession,
    events: List[EventCreate],
    request_id: str,
) -> BatchReceipt:
    """Persist a batch of validated events atomically, with an audit row."""
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
    await cache_delete_pattern(f"{ANOMALIES_CACHE_PREFIX}:*")
    return BatchReceipt(
        batch_id=batch.id, request_id=request_id, accepted=len(events), rejected=0
    )
