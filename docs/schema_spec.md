# Schema Spec — MICRO-1.2 (read this before coding)

This is the SPEC, not the solution. Implement it in src/models/database.py.

## Table: events (hot write path — 1000+ inserts/sec)
| column        | type                      | constraints                    |
|---------------|---------------------------|--------------------------------|
| id            | BIGINT (autoincrement)    | PK                             |
| event_type    | VARCHAR(50)               | NOT NULL                       |
| user_id       | BIGINT                    | NOT NULL                       |
| amount        | NUMERIC(12,2)             | nullable                       |
| payload       | JSONB                     | nullable                       |
| occurred_at   | TIMESTAMPTZ               | NOT NULL (client event time)   |
| ingested_at   | TIMESTAMPTZ               | NOT NULL, server default now() |
| anomaly_score | DOUBLE PRECISION          | nullable (NULL = not scored)   |
| is_anomaly    | BOOLEAN                   | server default false           |
| model_version | VARCHAR(20)               | nullable                       |

Indices on events:
1. idx_events_user_time      → (user_id, occurred_at DESC)
2. idx_events_occurred_at    → (occurred_at DESC)
3. idx_events_anomalies      → (occurred_at DESC) WHERE is_anomaly = TRUE  ← PARTIAL

## Table: model_registry
| column        | type             | constraints              |
|---------------|------------------|--------------------------|
| id            | INT autoincr     | PK                       |
| version       | VARCHAR(20)      | NOT NULL, UNIQUE         |
| trained_at    | TIMESTAMPTZ      | NOT NULL                 |
| f1_score      | DOUBLE PRECISION | nullable                 |
| training_rows | BIGINT           | nullable                 |
| is_active     | BOOLEAN          | server default false     |
| artifact_path | VARCHAR(255)     | nullable                 |

## Table: ingestion_batches
| column       | type          | constraints              |
|--------------|---------------|--------------------------|
| id           | BIGINT autoin | PK                       |
| request_id   | VARCHAR(64)   | NOT NULL  ← ties to X-Request-ID from your middleware |
| event_count  | INT           | NOT NULL                 |
| failed_count | INT           | server default 0         |
| started_at   | TIMESTAMPTZ   | NOT NULL                 |
| completed_at | TIMESTAMPTZ   | nullable                 |

## Design decisions you must be able to defend in the PR (and interviews)

1. Why BIGINT/BIGSERIAL for events.id and not INT?
To avoid int overflow.
INT max ≈ 2.147 billion
At 1,000 inserts/sec → 2.147B ÷ 1,000 ÷ 86,400 ≈ ~25 days to exhaustion

And the kicker: when a serial column overflows, inserts start failing in production — this is a famous real-world outage pattern. The cost of BIGINT is 4 extra bytes per row, which is nothing. Write it exactly like that in docs/schema.md: cheap insurance vs. catastrophic failure mode.
2. Why TIMESTAMPTZ everywhere, never TIMESTAMP?
The TIMESTAMPZ is used when the services are deployed in microservice from and in multileple region. Since the only TIMESTAMP stores the data in local timestamp it creates time conflict that leads to errors in analytical operations. Using TIMESTAMPTZ ensures your timestamps remain accurate and uniform across all regions.
3. Why BOTH occurred_at and ingested_at?
The two timestamps come from two different clocks:

occurred_at — when the event actually happened, on the client's side. The mobile app records the purchase at 14:03:07 its time. This value arrives inside the request payload.
ingested_at — when our server wrote the row. This is server_default=now() — our clock, not theirs.

Why they diverge, and why we need both:

Late-arriving events. A phone goes offline in the metro, the user makes a purchase, the app syncs 40 minutes later. occurred_at = 14:03, ingested_at = 14:43. If we only had one timestamp, the event would appear to have happened at the wrong time — which corrupts your anomaly features ("burst of purchases at 14:43!") in MICRO-3.1.
Client clock skew. Client clocks are wrong, sometimes wildly (misconfigured devices, timezone bugs). ingested_at is the only timestamp we can trust.
Different queries want different columns. Analytics/ML asks "what happened between 2–3 PM?" → occurred_at. Ops asks "what did we receive in the last 5 minutes / is the pipeline lagging?" → ingested_at. And ingested_at - occurred_at gives you a lag metric — that's the closest thing to your "time taken" idea, but it measures delivery delay, not processing duration.
4. Why is the anomaly index PARTIAL? What % of the table does it cover?
"Hot query only touches ~2% of rows, so index only those" — yes, that's the read-side argument, and it's right. Two sharpeners for your doc:

Size: the index holds ~2,000 entries instead of 100,000 → ~50x smaller → effectively always in memory → faster scans.
The write side, which most people miss: every index on a table must be updated on every matching insert. Because 98% of your inserts have is_anomaly = false, they skip this index entirely — zero maintenance cost on the hot ingestion path. A partial index is one of the rare optimizations that makes reads faster and writes cheaper at the same time. Put that sentence in the doc; it's the best line in the whole schema.
5. Why is there NO index on event_type alone?
 index columns where a typical predicate selects a small fraction of rows (high selectivity). user_id (5,000 distinct values → ~0.02% per user) qualifies; event_type (5 values → ~20% each) does not. And if we ever need "purchases in the last hour," the answer is a composite (event_type, occurred_at) — where the time column restores selectivity — not event_type alone.
Write your answers in docs/schema.md (ticket 1.2d). If you can't answer one,
that's a question for the tech lead — ask.

Query	Likely plan	The one-sentence explanation
recent_anomalies	Seq Scan or Index Only Scan (post-vacuum)	count(*) needs visibility checks; after VACUUM the partial index may enable an index-only scan
per_user_history	Index Scan, no Sort node	composite (user_id, occurred_at DESC) returns rows pre-sorted — the leftmost-prefix win
time_window_wide	Seq Scan	~50% of rows → too many to make an index worthwhile → Seq Scan is optimal
time_window_narrow	Index Scan	~3% of rows → selective enough that the index wins → the tipping point

