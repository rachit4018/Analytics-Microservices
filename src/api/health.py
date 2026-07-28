"""Database health check — MICRO-1.4 T3.

Tests: pytest tests/test_session.py -k health

A health check that actually runs a query proves the POOL works, not just that
the process is alive. Load balancers and k8s liveness probes hit this.
"""

# TODO(dev) T3: imports
#   from fastapi import APIRouter, Depends
#   from sqlalchemy import text
#   from sqlalchemy.ext.asyncio import AsyncSession
#   from src.models.session import get_db

# TODO(dev) T3: router = APIRouter(prefix="/health", tags=["health"])


# TODO(dev) T3: GET /health/db
#   - inject the session via Depends(get_db)
#   - run: await session.execute(text("SELECT 1"))
#   - return {"database": "ok"} on success
#
#   @router.get("/db")
#   async def db_health(session: AsyncSession = Depends(get_db)):
#       ...
