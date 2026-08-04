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

# from django.conf.locale import tr
import redis.asyncio as redis
from fastapi.encoders import jsonable_encoder

# TODO(dev) T1: import redis.asyncio as redis

logger = logging.getLogger("analytics.cache")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_TTL_SECONDS = 30


# TODO(dev) T1: module-level client
#   _client = redis.from_url(REDIS_URL, decode_responses=True)
#
#   decode_responses=True means you get str back instead of bytes — saves a
#   .decode() on every read.
_client = redis.from_url(REDIS_URL, decode_responses=True)


async def cache_get(key: str) -> Optional[Any]:
    """Return the deserialized value, or None on miss OR on any Redis failure.

    TODO(dev) T1:
      try:
          raw = await _client.get(key)
          return json.loads(raw) if raw else None
      except Exception:
          logger.warning("cache get failed, degrading to db", extra={"key": key})
          return None

    Note the bare `except Exception` — normally a smell, but here it is the
    POINT: no Redis error may ever reach the caller. Justify this in your PR.
    """
    try:
        raw = await _client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("cache get failed, degrading to db", extra={"key": key})
        return None


async def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
    """Store a JSON-serializable value with a TTL. Never raises.

    TODO(dev) T1:
      try:
          await _client.set(key, json.dumps(value), ex=ttl)
          return True
      except Exception:
          logger.warning(...)
          return False

    Careful: your AnomalyResponse contains Decimal and datetime, which
    json.dumps cannot serialize. You solved this exact problem in the error
    handler — same tool applies here.
    """
    try:
        await _client.set(key, jsonable_encoder(value), ex=ttl)
        return True
    except Exception:
        logger.warning("cache set failed, degrading to db", extra={"key": key})
        return False


async def cache_delete(key: str) -> bool:
    """Delete a key (used for invalidation on write). Never raises.

    TODO(dev) T1: implement with the same try/except shape.
    """
    try:
        await _client.delete(key)
        return True
    except Exception:
        logger.warning("cache delete failed, degrading to db", extra={"key": key})
        return False


async def close_cache() -> None:
    """Close the Redis connection pool — called from main.py lifespan.

    TODO(dev) T5: await _client.aclose()
    """
    try:
        await _client.aclose()
    except Exception:
        logger.warning("redis connection pool closing error")
