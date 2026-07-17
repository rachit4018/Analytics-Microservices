"""SQLAlchemy ORM models — MICRO-1.2a.

Implement per docs/schema_spec.md. Tests: pytest tests/test_schema.py -k orm
Docs you'll need:
  https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html
  https://docs.sqlalchemy.org/en/20/dialects/postgresql.html (JSONB, partial index)
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Index, Numeric, String, func, text, Integer
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION
from typing import Any, Dict, Optional

class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # TODO(dev): event_type — String(50), NOT NULL
    event_type : Mapped[String] = mapped_column(String(50), nullable=False)

    # TODO(dev): user_id — BigInteger, NOT NULL
    user_id : Mapped[int] = mapped_column(BigInteger, nullable = False)
    # TODO(dev): amount — Numeric(12, 2), nullable
    amount : Mapped[Numeric] = mapped_column(Numeric(12,2), nullable=True)

    # TODO(dev): payload — JSONB, nullable
    payload : Mapped[Optional[Dict[str,Any]]] = mapped_column(JSONB,nullable=True)
    # TODO(dev): occurred_at — TIMESTAMP(timezone=True), NOT NULL
    occurred_at : Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    # TODO(dev): ingested_at — TIMESTAMP(timezone=True), NOT NULL,
    #            server_default=func.now()
    ingested_at : Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    # TODO(dev): anomaly_score — float, nullable
    anomaly_score : Mapped[float] = mapped_column(DOUBLE_PRECISION, nullable=True)
    # TODO(dev): is_anomaly — Boolean, server_default "false"
    is_anomaly : Mapped[Boolean] = mapped_column(Boolean, server_default="False")
    # TODO(dev): model_version — String(20), nullable
    model_version : Mapped[String] = mapped_column(String(20), nullable = True)
    __table_args__ = (
        # TODO(dev): idx_events_user_time on (user_id, occurred_at DESC)
        # TODO(dev): idx_events_occurred_at on (occurred_at DESC)
        # TODO(dev): idx_events_anomalies on (occurred_at DESC)
        #            PARTIAL: postgresql_where=(is_anomaly == True)
        #            <-- this kwarg is the whole point of the ticket
        Index(
            "idx_events_user_time",
            "user_id",
            text("occured_at DESC"),
        ),
        Index(
            "idx_events_occured_at",
            text("occured_at DESC"),

        ),
        Index(
            "idx_events_anomalies",     # The unique index name in the database
            text("occured_at DESC"),            
            postgresql_where="is_anomaly = true"  #  THE CRITICAL CLAUSE: Only map anomaly rows!
        ),
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(primary_key=True)

    # TODO(dev): version — String(20), unique=True, NOT NULL
    version : Mapped[String] = mapped_column(String(20), unique=True, nullable =False)
    # TODO(dev): trained_at — TIMESTAMPTZ, NOT NULL
    trained_at : Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True),nullable=False)
    # TODO(dev): f1_score — float, nullable
    f1_score: Mapped[float] = mapped_column(DOUBLE_PRECISION)
    # TODO(dev): training_rows — BigInteger, nullable
    training_rows: Mapped[BigInteger] = mapped_column(BigInteger)
    # TODO(dev): is_active — Boolean, server_default "false"
    is_active: Mapped[Boolean] = mapped_column(Boolean, server_default="False")
    # TODO(dev): artifact_path — String(255), nullable
    artifcat_path: Mapped[String] = mapped_column(String(255))

class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # TODO(dev): request_id — String(64), NOT NULL
    #            (this is the X-Request-ID from your tracing middleware!)
    request_id: Mapped[String] = mapped_column(String(64), nullable=False)
    # TODO(dev): event_count — int, NOT NULL
    event_count: Mapped[Integer] = mapped_column(Integer,nullable=False)
    # TODO(dev): failed_count — int, server_default "0"
    failed_count: Mapped[Integer] = mapped_column(Integer, server_default="0")
    # TODO(dev): started_at — TIMESTAMPTZ, NOT NULL
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    # TODO(dev): completed_at — TIMESTAMPTZ, nullable
    completed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))

