"""Pydantic request/response schemas — MICRO-1.3.

Tests: pytest tests/test_schemas.py -v

Pydantic v2 docs you'll need:
  https://docs.pydantic.dev/latest/concepts/fields/          (Field constraints)
  https://docs.pydantic.dev/latest/concepts/validators/      (field_validator)
  https://docs.pydantic.dev/latest/concepts/models/#model-config

Reference: your ORM models in src/models/database.py define the DB shape.
These define the API shape. They are NOT the same — see the ticket.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Must match the event_type values your seed script generates.
ALLOWED_EVENT_TYPES = {"purchase", "trade", "claim", "refund", "transfer"}

# How far into the future a client timestamp may be before we reject it.
MAX_FUTURE_SKEW_SECONDS = 300  # 5 minutes


class EventCreate(BaseModel):
    """One event as submitted by a client.

    TODO(dev) T1:
      model_config -> forbid unknown fields
      event_type   -> str, must be in ALLOWED_EVENT_TYPES
      user_id      -> int, must be > 0
      amount       -> Decimal | None, >= 0, max 12 digits, 2 decimal places
                      (hint: Field(..., ge=..., max_digits=..., decimal_places=...))
      payload      -> dict | None
      occurred_at  -> datetime, MUST be timezone-aware, MUST NOT be more than
                      MAX_FUTURE_SKEW_SECONDS in the future
                      (hint: @field_validator("occurred_at") — check
                       value.tzinfo is not None, then compare to now)

    Deliberately ABSENT (server-owned — a client must never set these):
      id, ingested_at, anomaly_score, is_anomaly, model_version
    """

    model_config = ConfigDict(extra="forbid")
    event_type: str
    user_id: int = Field(..., gt=0)
    amount: Optional[Decimal] = Field(
        None, ge=Decimal("0.00"), max_digits=12, decimal_places=2
    )
    payload: Optional[dict[str, Any]] = None
    occurred_at: datetime
    # TODO(dev): validators

    @field_validator("event_type")
    @classmethod
    def validate_event_field(cls, value: str) -> str:
        if value not in ALLOWED_EVENT_TYPES:
            raise ValueError(
                f"Invalid Event type. Must be one from: {' ,'.join(ALLOWED_EVENT_TYPES)}"
            )
        return value

    @field_validator("occurred_at")
    @classmethod
    def validate_timezone_and_skew(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("occurred_at must be a timezone-aware datetime")

        now_aware = datetime.now(timezone.utc)
        time_difference = (value - now_aware).total_seconds()
        if time_difference > MAX_FUTURE_SKEW_SECONDS:
            raise ValueError(
                f"occurred_at cannot be more than {MAX_FUTURE_SKEW_SECONDS} seconds in the future"
            )
        return value


class EventBulkCreate(BaseModel):
    """A batch of events for POST /events.

    TODO(dev) T2:
      events -> list[EventCreate], at least 1, at most 1000
                (hint: Field(..., min_length=1, max_length=1000))

    Why cap at 1000? An unbounded list is a memory DoS vector, and your
    bulk INSERT batches at 5000 anyway (see seed script benchmark).
    """

    model_config = ConfigDict(extra="forbid")
    events: List[EventCreate] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="A bounded batch of events. Capped at 1000 to prevent memory DoS.",
    )


class EventResponse(BaseModel):
    """An event as returned by the API. Built FROM an ORM object.

    TODO(dev) T3:
      model_config -> from_attributes=True  (lets model_validate(orm_obj) work)
      fields: id, event_type, user_id, amount, payload, occurred_at,
              ingested_at, anomaly_score, is_anomaly, model_version
      Nullable ones mirror the DB: amount, payload, anomaly_score,
      model_version are Optional.
    """

    # TODO(dev): model_config + fields
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    user_id: int
    amount: Decimal | None = None
    payload: dict[str, Any] | None
    occurred_at: datetime
    ingested_at: datetime
    anomaly_score: float | None = None
    is_anomaly: bool
    model_version: str | None = None


class AnomalyResponse(BaseModel):
    """Trimmed shape for GET /anomalies — only what a dashboard needs.

    TODO(dev) T4:
      model_config -> from_attributes=True
      EXACTLY these fields: id, user_id, amount, occurred_at,
                            anomaly_score, model_version
      (No payload, no event_type — smaller payload over the wire.)
    """

    # TODO(dev): model_config + fields
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    amount: Decimal | None = None
    occurred_at: datetime
    anomaly_score: float | None = None
    model_version: str | None = None


class ErrorResponse(BaseModel):
    """Error contract. MUST match what your error_handler middleware emits.

    TODO(dev) T5:
      error_code -> str, required   e.g. "VALIDATION_ERROR"
      message    -> str, required
      request_id -> str, required   (the X-Request-ID from tracing middleware)
      details    -> optional, any JSON-ish structure
    """

    # TODO(dev): declare fields
    error_code: str
    message: str
    request_id: str
    details: dict[str, Any] | list[Any] | None = None


class BatchReceipt(BaseModel):
    """What POST /events returns. Consumed by MICRO-2.1.

    TODO(dev) T6:
      batch_id   -> int, required   (ingestion_batches.id)
      request_id -> str, required
      accepted   -> int, required, >= 0
      rejected   -> int, required, >= 0
    """

    # TODO(dev): declare fields
    batch_id: int
    request_id: str
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
