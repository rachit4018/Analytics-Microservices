2026-07 | Amended test: assert partial index exists + latency, not planner choice | verified with ANALYZE'd stats (rows=2037 accurate) that planner still prefers idx_events_occurred_at; access path is data-dependent and not a valid assertion

2026-07| the scripts runs as module using -m command - > python3 -m scripts.seed_events
## MICRO-1.2 — schema (already decided, backfilled)

2026-07 | BIGSERIAL for events.id | INT exhausts in ~25 days at 1000 inserts/sec; overflow = failed inserts in prod
2026-07 | TIMESTAMPTZ everywhere | store UTC-aware; naive timestamps lose meaning across zones
2026-07 | Split occurred_at / ingested_at | client event time vs server receive time; late arrivals and clock skew
2026-07 | No FK on events.user_id | users live in another service; FK cost on hot write path; events outlive users
2026-07 | JSONB for payload | structured core columns + flexible tail; JSONB is queryable and indexable, JSON is not
2026-07 | Partial index on is_anomaly | ~2% of rows: 50x smaller index AND 98% of inserts skip maintaining it
2026-07 | No index on event_type alone | 5 distinct values ≈ 20% selectivity; planner would ignore it while inserts still pay
2026-07 | Audit gates on latency, not scan type | Seq Scan is often the optimal plan; asserting scan type failed a healthy schema

## MICRO-1.3 — validation

TODO(dev): add one line each for —
  - rejecting naive datetimes rather than assuming UTC
  - allowing 5 min of future clock skew rather than zero
  - extra="forbid" rather than ignoring unknown fields
  - separate Create and Response models rather than one shared model
  - Decimal for amount rather than float
