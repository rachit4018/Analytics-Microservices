"""GET /anomalies — MICRO-2.2 T2.

Your first READ endpoint. Demonstrates the cache-aside pattern.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.database import Event
from src.models.schemas import AnomalyResponse
from src.models.session import get_db
from src.services.cache import cache_get, cache_set


router = APIRouter(tags=["anomalies"])

ANOMALIES_CACHE_PREFIX = "anomalies"


def anomalies_cache_key(limit: int) -> str:
    """Key includes the limit — /anomalies?limit=10 and ?limit=50 are
    DIFFERENT results and must not share a cache entry.
    TODO(dev) T2: return f"{ANOMALIES_CACHE_PREFIX}:limit={limit}"
    """
    return f"{ANOMALIES_CACHE_PREFIX}:limit={limit}"


@router.get("/anomalies", response_model=list[AnomalyResponse])
async def list_anomalies(
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    key = anomalies_cache_key(limit)
    cached = await cache_get(key)
    if cached is not None:
        return cached
    stmt = (
        select(Event)
        .where(Event.is_anomaly.is_(True))
        .order_by(Event.occurred_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    events = result.scalars().all()
    payload = [AnomalyResponse.model_validate(e) for e in events]
    await cache_set(key, payload)
    return payload
