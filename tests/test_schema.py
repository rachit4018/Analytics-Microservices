"""MICRO-1.2 acceptance tests — WRITTEN BY TECH LEAD, DO NOT EDIT.

Your implementation must make these pass:
  pytest tests/test_schema.py -k orm        (after 1.2a)
  pytest tests/test_schema.py -k migration  (after 1.2b)
  pytest tests/test_schema.py -k seed       (after 1.2c — run the seed first)
  pytest tests/test_schema.py               (everything, before raising PR)

Requires: docker-compose postgres up, DATABASE_URL env var (or default).
"""

import os
import subprocess

import pytest
from sqlalchemy import create_engine, inspect, text

SYNC_URL = os.environ.get(
    "DATABASE_URL_SYNC", "postgresql+psycopg2://postgres:postgres@localhost:5432/analytics"
)


@pytest.fixture(scope="module")
def engine():
    return create_engine(SYNC_URL)


@pytest.fixture(scope="module")
def insp(engine):
    return inspect(engine)


# ---------- 1.2a: ORM model shape ----------

class TestORM:
    def test_orm_models_importable(self):
        from src.models.database import Base, Event, ModelRegistry, IngestionBatch 
        assert {"events", "model_registry", "ingestion_batches"} <= set(
            Base.metadata.tables.keys()
        )

    def test_orm_events_columns(self):
        from src.models.database import Base
        cols = Base.metadata.tables["events"].columns
        expected = {
            "id", "event_type", "user_id", "amount", "payload",
            "occurred_at", "ingested_at", "anomaly_score", "is_anomaly",
            "model_version",
        }
        assert expected <= {c.name for c in cols}
        assert cols["occurred_at"].type.timezone is True, "use TIMESTAMPTZ"
        assert str(cols["id"].type) == "BIGINT", "events.id must be BIGINT"

    def test_orm_registry_version_unique(self):
        from src.models.database import Base
        version = Base.metadata.tables["model_registry"].columns["version"]
        assert version.unique is True

    def test_orm_partial_index_defined(self):
        from src.models.database import Base
        idx = {i.name: i for i in Base.metadata.tables["events"].indexes}
        assert "idx_events_anomalies" in idx, "partial anomaly index missing"
        assert (
            idx["idx_events_anomalies"].dialect_options["postgresql"]["where"]
            is not None
        ), "idx_events_anomalies must be PARTIAL (postgresql_where=...)"


# ---------- 1.2b: migration actually applied ----------

class TestMigration:
    def test_migration_tables_exist(self, insp):
        tables = insp.get_table_names()
        for t in ("events", "model_registry", "ingestion_batches"):
            assert t in tables, f"{t} missing — did you run alembic upgrade head?"

    def test_migration_indices_exist(self, insp):
        names = {i["name"] for i in insp.get_indexes("events")}
        for expected in (
            "idx_events_user_time",
            "idx_events_occurred_at",
            "idx_events_anomalies",
        ):
            assert expected in names, f"{expected} missing from database"

    def test_migration_partial_index_in_db(self, engine):
        sql = text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='events' AND indexname='idx_events_anomalies'"
        )
        with engine.connect() as c:
            indexdef = c.execute(sql).scalar()
        assert indexdef and "WHERE" in indexdef.upper(), (
            "idx_events_anomalies exists but is NOT partial in the DB — "
            "alembic autogenerate dropped the WHERE clause; fix the migration"
        )

    def test_migration_downgrade_upgrade_roundtrip(self):
        env = {**os.environ}
        down = subprocess.run(
            ["alembic", "downgrade", "base"], capture_output=True, env=env
        )
        up = subprocess.run(
            ["alembic", "upgrade", "head"], capture_output=True, env=env
        )
        assert down.returncode == 0, down.stderr.decode()[:500]
        assert up.returncode == 0, up.stderr.decode()[:500]


# ---------- 1.2c: seed data quality ----------

class TestSeed:
    def test_seed_row_count(self, engine):
        with engine.connect() as c:
            n = c.execute(text("SELECT count(*) FROM events")).scalar()
        assert n >= 100_000, f"expected >=100k rows, got {n} — run the seed script"

    def test_seed_anomaly_rate(self, engine):
        with engine.connect() as c:
            rate = c.execute(
                text("SELECT avg(is_anomaly::int) FROM events")
            ).scalar()
        assert 0.01 <= float(rate) <= 0.04, f"anomaly rate {rate} outside 1-4%"

    def test_seed_anomalies_look_anomalous(self, engine):
        sql = text(
            "SELECT avg(amount) FILTER (WHERE is_anomaly) / "
            "NULLIF(avg(amount) FILTER (WHERE NOT is_anomaly), 0) FROM events"
        )
        with engine.connect() as c:
            ratio = c.execute(sql).scalar()
        assert float(ratio) > 10, (
            f"anomalous amounts only {ratio:.1f}x normal — ticket says 50-100x"
        )

    def test_seed_user_distribution_power_law(self, engine):
        sql = text(
            "SELECT max(cnt)::float / avg(cnt) FROM "
            "(SELECT count(*) cnt FROM events GROUP BY user_id) s"
        )
        with engine.connect() as c:
            skew = c.execute(sql).scalar()
        assert float(skew) > 5, "user_id distribution looks uniform, not power-law"


# ---------- 1.2d: the indices actually get used ----------

class TestQueryPlans:
    def test_plan_anomaly_query_uses_partial_index(self, engine):
        sql = text(
            "EXPLAIN SELECT * FROM events WHERE is_anomaly "
            "ORDER BY occurred_at DESC LIMIT 50"
        )
        with engine.connect() as c:
            plan = "\n".join(r[0] for r in c.execute(sql))
        assert "idx_events_anomalies" in plan, (
            "planner is not using the partial index — check ANALYZE ran / "
            "index definition. Plan was:\n" + plan
        )

    def test_plan_user_history_uses_index(self, engine):
        sql = text(
            "EXPLAIN SELECT * FROM events WHERE user_id = 42 "
            "ORDER BY occurred_at DESC LIMIT 100"
        )
        with engine.connect() as c:
            plan = "\n".join(r[0] for r in c.execute(sql))
        assert "idx_events_user_time" in plan, "Plan was:\n" + plan
