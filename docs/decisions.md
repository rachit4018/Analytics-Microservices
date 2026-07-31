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

TODO(dev): one line each, with reasoning —
  - one engine for whole app vs per-request  | ...
  The key mechanism to name is cost. Creating an engine means establishing TCP connections and authenticating with Postgres — expensive, ~milliseconds each. Per-request, you'd pay that on every single call and exhaust Postgres's connection limit under load. One engine creates the connections once, keeps them in a pool, and hands them out/returns them per request. Tighter version: "An engine owns a connection pool; creating connections is expensive (TCP + auth) and Postgres caps total connections. One shared engine amortizes that cost across all requests and bounds total connections, instead of each request opening its own.
  - pool_pre_ping=True                        | ...
    connections in the pool can go stale — Postgres restarts, a network blip drops them, or a firewall times out an idle connection. Without pre-ping, the pool hands your request a dead connection and the query blows up. pool_pre_ping=True runs a cheap SELECT 1 before handing over any pooled connection; if it's dead, the pool quietly discards it and gets a fresh one. Name the failure it prevents: "Guards against stale/dead pooled connections after a DB restart or idle timeout — pre-ping tests the connection cheaply before use and transparently replaces dead ones, so requests don't fail on a broken handle.
  - expire_on_commit=False for async          | ...
  fter commit, the default expires object attributes so the next access reloads them via a query. In async that lazy reload needs I/O at attribute-access time, which isn't awaitable and errors. False keeps attributes usable post-commit — essential for returning an object in a response after saving it.
  - rollback on any exception + re-raise       | ...
  Roll back so a failed request never commits a partial unit of work (consistency). Re-raise so the exception still propagates to the error-handler middleware, which turns it into a structured error response with the request_id — swallowing it would hide the failure from the client.
  - test isolation: truncate vs rollback       | ... (tech lead recommended truncate)
  MY RECOMMENDATION FOR THIS TICKET: **Option A (truncate).**
Reasoning: 1.4 has few DB-writing tests, async transaction-rollback fixtures
are fiddly (nested transactions + savepoints), and "simple and obviously
correct" beats "fast and clever" for infrastructure you'll debug at 2am. We
revisit Option B in MICRO-2.1 when write-heavy endpoint tests make speed matter.


2026-07 | NullPool for engine when TESTING=1 | asyncpg connections bind to their event loop; pooling caches them across pytest's per-test loops → "attached to a different loop". NullPool opens fresh per session. Prod keeps the real pool.
2026-07 | asyncio_mode=auto | async tests run without per-test marks; silences pytestmark-on-sync-test warnings
 Think of a database connection like a phone call, and the "event loop" as the specific phone line that call is running on. In async Python, once you start a call on a particular line, it only works on that line — you can't pick up the handset on a different line and expect the same call to be there. Now, a connection pool is like keeping a few calls on hold so you can reuse them instead of dialing fresh every time — great for a real running app, because the app has one phone line open all day. But when you run tests, the testing tool hangs up the whole phone system and sets up a brand-new line for each test. So a pooled connection that was put on hold during one test tries to get reused in the next test — except that line was already torn down. The connection reaches for a phone line that no longer exists, and you get "event loop is closed" or "attached to a different loop." The fix, NullPool, simply says "don't put any calls on hold during tests" — every test dials a fresh connection on its own current line and hangs up cleanly when done. Nothing is ever carried over from a dead line, so the whole class of error disappears. In production we keep the pool (dialing fresh every time is wasteful when you've got one line open all day), but in tests, throwing the connection away each time is exactly what keeps things clean.
| Error handler must jsonable_encode ValidationError details | raw exc.errors() contains Decimal/datetime; json.dumps can't serialize them → handler crashed → 422 became 500
| Ingestion tests use autouse truncate fixture for isolation | re-runs accumulated rows; per-test unique ids masked it; truncate scoped to write tables gives real isolation (revisited from Sprint 2 deferral)

<!-- 
test-ingestion:
	psql -h localhost -p 5432 -d test_db -c "TRUNCATE events, ingestion_batches RESTART IDENTITY CASCADE;"
	TESTING=1 pytest tests/test_ingestion.py -v

test-schema:
	TESTING=1 pytest tests/test_schema.py tests/test_schemas.py tests/test_session.py -v
test: test-schema test-ingestions -->
