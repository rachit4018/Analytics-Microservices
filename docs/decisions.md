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
  - rejecting naive datetimes rather than assuming UTC from client side
  it eliminates ambiguity (No assumption), catches client side bugs, Idempotency

  - allowing 5 min of future clock skew rather than zero
  no two server has exact time diff. 5 minutes gives to handle network latency and imperfectly sync clocks, also 0 breaks valid traffic due to minor clock difference where as 1 hour opens door for data manipulation, such as clients reporting events that has not happend.
  - extra="forbid" rather than ignoring unknown fields
  prevents ambigeuous fields like urse_id rather later throwing missing field error, prevents mass assignment vulneabilities, saves bandwidth in case of client sending huge payload and then servcer parsing it .
  - separate Create and Response models rather than one shared model
  the fields can be different and not all the fields needed to show on client side, saves bandwidth and again errors can be easily managed.EventCreate omitting is_anomaly/anomaly_score means a client physically cannot claim their own fraudulent transaction is non-anomalous. Lead with that: "Separate models let the API accept only client-owned fields (Create) while returning server-owned ones (Response) — a client cannot set is_anomaly or anomaly_score, which would otherwise be a data-integrity hole. Also trims response payloads to what each consumer needs."
  - Decimal for amount rather than float
 float is base-2, and the problem is that many base-10 decimals (like 0.1) have no exact binary representation, so they're stored as tiny approximations that accumulate rounding error. Fix: "Money needs exact decimal representation. Floats are binary and can't represent values like 0.10 exactly, so rounding errors accumulate — unacceptable for financial amounts. Decimal stores base-10 exactly
 - Why does extra="forbid" belong on EventCreate but not EventResponse?
 Exactly right. Requests come from the client — untrusted, so you lock the door with extra="forbid". Responses go to the client, built from your own trusted ORM objects — nothing to defend against, and forbidding extras would just make the model brittle when you add a column later. Data direction determines trust, trust determines strictnesss
