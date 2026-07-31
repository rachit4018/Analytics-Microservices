"""POST /events — MICRO-2.1 T2, T3.

Thin endpoint: read request_id, delegate to the service, return the receipt.
"""

import uuid
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.session import get_db
from src.models.schemas import EventBulkCreate, BatchReceipt
from src.services.ingestion import ingest_events


# TODO(dev) T2: router = APIRouter(tags=["events"])
router = APIRouter(tags=["events"])


@router.post(
    "/events", status_code=status.HTTP_202_ACCEPTED, response_model=BatchReceipt
)
async def create_events(
    payload: EventBulkCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    print("Endpoint reached")
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    print("Endpoint:", getattr(request.state, "request_id", None))
    return await ingest_events(session, payload.events, request_id)
