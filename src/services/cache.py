"""Redis cache wrapper — MICRO-2.2 T1.

EVERY method here must be failure-safe: if Redis is down, log a warning and
return None / False. Never raise. The caller treats None as a cache miss and
falls through to Postgres.

Tests: pytest tests/test_cache.py -v
Docs: https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html
"""

import json
import logging
import os

# import re
from typing import Any, Optional

import redis.asyncio as redis
from fastapi.encoders import jsonable_encoder


logger = logging.getLogger("analytics.cache")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_TTL_SECONDS = 30
_client = redis.from_url(REDIS_URL, decode_responses=True)


async def cache_get(key: str) -> Optional[Any]:
    try:
        raw = await _client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("cache get failed, degrading to db", extra={"key": key})
        return None


async def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
    try:

        await _client.set(key, json.dumps(jsonable_encoder(value)), ex=ttl)
        return True
    except Exception:
        logger.warning("cache set failed, degrading to db", extra={"key": key})
        return False


async def cache_delete(key: str) -> bool:
    try:
        await _client.delete(key)
        return True
    except Exception:
        logger.warning("cache delete failed, degrading to db", extra={"key": key})
        return False


async def close_cache() -> None:
    try:
        await _client.aclose()
    except Exception:
        logger.warning("redis connection pool closing error")


async def cache_delete_pattern(pattern: str) -> int:
    """Delete all keys matching a pattern. Never raises."""
    try:
        deleted = 0
        async for key in _client.scan_iter(match=pattern):
            await _client.delete(key)
            deleted += 1
        return deleted
    except Exception:
        logger.warning("cache pattern delete failed", extra={"pattern": pattern})
        return 0
