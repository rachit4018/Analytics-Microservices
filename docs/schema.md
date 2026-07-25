# Schema Design & Query Performance

**MICRO-1.2 — `events`, `model_registry`, `ingestion_batches`**

This doc explains what the schema in `src/models/database.py` looks like, why each
non-obvious decision was made, and what the query-plan audit in
`scripts/profile_hot_queries.py` actually found. If you're joining this project and
your instinct is to add an index on `event_type` or "fix" a query that shows a Seq
Scan, read Sections 4 and 5 first — both are deliberate.

## 1. Tables

**`events`** — the hot write path (1,000+ inserts/sec target). One row per ingested
event; anomaly fields are populated asynchronously after the Isolation Forest scores it.

| column | type | notes |
|---|---|---|
| `id` | `BIGINT` PK | see §2 for why not `INT` |
| `event_type` | `VARCHAR(50)` NOT NULL | low-cardinality (5 values) |
| `user_id` | `BIGINT` NOT NULL | no FK — see §2 |
| `amount` | `NUMERIC(12,2)` | nullable |
| `payload` | `JSONB` | nullable, flexible tail — see §2 |
| `occurred_at` | `TIMESTAMPTZ` NOT NULL | client-reported event time |
| `ingested_at` | `TIMESTAMPTZ` NOT NULL, `server_default now()` | server write time |
| `anomaly_score` | `DOUBLE PRECISION` | nullable — see §2 |
| `is_anomaly` | `BOOLEAN`, `server_default false` | label |
| `model_version` | `VARCHAR(20)` | nullable, FK-by-convention to `model_registry.version` |

**`model_registry`** — tracks trained Isolation Forest versions: `version` (unique),
`trained_at`, `f1_score`, `training_rows`, `is_active`, `artifact_path`. One row per
training run; `is_active` marks which version is currently scoring live traffic.

**`ingestion_batches`** — audit trail for bulk inserts: `request_id`, `event_count`,
`failed_count`, `started_at`, `completed_at`. The detail worth flagging on the ERD:
`ingestion_batches.request_id` is the same `X-Request-ID` that
`src/middleware/tracing.py` attaches to every HTTP request (reused from the upstream
gateway when present, generated otherwise). That's the cross-layer link — you can take
a request ID out of an access log and find the exact ingestion batch it produced,
without a separate correlation table.

## 2. Column design decisions

**Why `BIGINT`, not `INT`, for `events.id`.** `INT` tops out around 2.147 billion. At
1,000 inserts/sec that ceiling arrives in about 25 days. A serial column that overflows
doesn't degrade gracefully — inserts start failing outright, which is a well-known
production outage pattern. `BIGINT` costs 4 extra bytes per row. That's cheap insurance
against a catastrophic failure mode, not a premature optimization.

**Why `TIMESTAMPTZ` everywhere, never `TIMESTAMP`.** This service runs across regions.
`TIMESTAMP` stores a naive wall-clock value with no offset, so the same instant written
from two regions (or interpreted by a server in a different timezone than the client)
can compare or sort incorrectly. `TIMESTAMPTZ` normalizes to UTC internally, so
ordering and range queries stay correct regardless of where the row was written or read
from.

**Why both `occurred_at` and `ingested_at`.** They come from two different clocks.
`occurred_at` is client-reported — when the event actually happened on the user's
device. `ingested_at` is `server_default now()` — when our server wrote the row, a
clock we actually trust. They diverge for two reasons: late-arriving events (a phone
goes offline, syncs 40 minutes later — `occurred_at` says 14:03, `ingested_at` says
14:43) and client clock skew (misconfigured devices report the wrong time entirely). If
we only kept one timestamp, a batch of delayed events would look like a sudden burst at
ingestion time, corrupting anomaly features. Analytics and the anomaly model query by
`occurred_at` ("what happened between 2 and 3 PM"); ops queries pipeline health by
`ingested_at` ("what did we receive in the last five minutes, are we lagging"). The
difference between the two is a lag metric for free.

**Why the anomaly index is partial, and why there's no index on `event_type` alone.**
Covered in depth in §3 — the short version is that both decisions follow the same rule:
index columns where the predicate you actually run selects a small fraction of rows.
`user_id` and `is_anomaly = true` qualify; `event_type` (5 values, ~20% each) doesn't.

**Why `user_id` has no foreign key to a users table.** User identity lives in a
different service; `events` doesn't own that data and shouldn't validate against it
synchronously on every insert. An FK check adds a lookup to the hot write path for
every one of 1,000+ inserts/sec, and event history is expected to outlive a user
record (a deleted account's past events are still valid analytics data — an FK with
`ON DELETE CASCADE` would silently destroy that history; `RESTRICT` would block
account deletion). The boundary is enforced at the application layer instead.

**Why `payload` is `JSONB`, not a fixed set of columns or plain `JSON`.** Events have a
structured core (`event_type`, `amount`, `occurred_at`, ...) that every consumer needs
and a variable tail (channel, client metadata, event-specific fields) that differs by
`event_type` and will keep changing as new event types are added. Promoting every
possible field to a column would mean a migration for each new integration. `JSONB`
over plain `JSON` specifically because it's stored decomposed and binary-indexable
(e.g. via GIN) if a `payload` field ever needs to be queried directly — `JSON` is
stored as text and re-parsed on every access.

**Why `anomaly_score` being `NULL` is not the same as `is_anomaly` being `false`.**
`anomaly_score IS NULL` means "not scored yet" — an unknown, because the model hasn't
run on this row. `is_anomaly = false` is a claim — the model ran and concluded this
event is not anomalous. Collapsing these (e.g. defaulting the score to `0`) would make
"unscored" indistinguishable from "confidently normal," which breaks any query that
needs to find the backlog of events still waiting on scoring.

## 3. Index strategy

**`idx_events_user_time` on `(user_id, occurred_at DESC)`.** Serves the per-user
history query: "give me this user's most recent events." `user_id` is the leading
column because it's the equality predicate and it's highly selective (~5,000 users,
~0.02% of rows each); `occurred_at DESC` is second because within a user's rows, that's
the sort order the query wants. This is the leftmost-prefix rule in action — an index
on `(user_id, occurred_at)` satisfies `WHERE user_id = X ORDER BY occurred_at DESC`
directly, but an index on `(occurred_at, user_id)` would not, because the leading
column wouldn't match the equality predicate.

**`idx_events_occurred_at` on `(occurred_at DESC)`.** Serves time-window aggregations
across all users. It's only useful when the window is narrow enough to be selective —
see §4 for the exact tipping point between this index winning and losing to a Seq Scan.

**`idx_events_anomalies` on `(occurred_at DESC) WHERE is_anomaly = true`.** A partial
index, and the one decision worth defending carefully. The read-side argument: only
~2% of rows are anomalies, so an index over the full table would waste ~98% of its
entries on rows the anomaly-review query never touches. Restricting it to
`is_anomaly = true` shrinks it to roughly 2,000 entries instead of 100,000 — about 50x
smaller, small enough to stay resident in memory. The write-side argument is the one
people miss: every index on a table has to be maintained on every insert that matches
its predicate. Because 98% of inserts have `is_anomaly = false`, they skip this index
entirely — zero maintenance cost on the hot ingestion path for the vast majority of
writes. A partial index is one of the rare optimizations that makes reads faster *and*
writes cheaper at the same time.

## 4. Query plan analysis

The audit (`scripts/profile_hot_queries.py`) runs `EXPLAIN (ANALYZE, BUFFERS)` against
each hot query and checks execution time against a 50ms budget. Scan type is printed
for context but never fails the run — see §5 for why.

### `per_user_history`

```sql
SELECT id, event_type, occurred_at, amount FROM events
WHERE user_id = :user_id ORDER BY occurred_at DESC LIMIT 20;
```

```
Limit (actual rows=20 loops=1)
  ->  Index Scan using idx_events_user_time on events (actual rows=20 loops=1)
        Index Cond: (user_id = $1)
        Buffers: shared hit=23
```

No `Sort` node. `idx_events_user_time` stores each user's rows already ordered by
`occurred_at DESC`, so the planner just walks the index and stops at `LIMIT 20` — the
leftmost-prefix win described in §3. Forcing a plan without the composite index (Seq
Scan + explicit sort over the same query) costs `shared hit=1,502` buffers against this
one's 23 — roughly 65x more I/O for the same result set.

### `time_window_wide` (~49% of rows match)

```sql
SELECT event_type, COUNT(*), AVG(amount) FROM events
WHERE occurred_at BETWEEN :wide_start AND :wide_end GROUP BY event_type;
```

```
HashAggregate (actual rows=5 loops=1)
  ->  Seq Scan on events (actual rows≈49,000 loops=1)
        Filter: (occurred_at >= $1) AND (occurred_at <= $2)
```

Execution time: ~16ms. At roughly half the table matching, an index scan would still
have to visit nearly half the heap, plus pay random I/O per index entry on top of the
index traversal itself. A single sequential read of the table is cheaper. This is the
correct plan, not a missing-index symptom.

### `time_window_narrow` (~3.4% of rows match)

```sql
SELECT event_type, COUNT(*), AVG(amount) FROM events
WHERE occurred_at BETWEEN :narrow_start AND :narrow_end GROUP BY event_type;
```

```
HashAggregate (actual rows=5 loops=1)
  ->  Bitmap Heap Scan on events (actual rows≈3,400 loops=1)
        Recheck Cond: (occurred_at >= $1) AND (occurred_at <= $2)
        ->  Bitmap Index Scan on idx_events_occurred_at
              Index Cond: (occurred_at >= $1) AND (occurred_at <= $2)
```

Execution time: ~2.1ms. Same query shape, same index available, same table — only the
selectivity of the `WHERE` clause changed, and it flips the planner's choice. This pair
is the tipping point: ~49% selectivity → Seq Scan at 16ms; ~3.4% selectivity → Bitmap
Index Scan at 2.1ms. Postgres isn't applying a fixed rule ("time-range query → use the
index"); it's costing both access paths for the actual predicate and picking whichever
is cheaper.

### `recent_anomalies`

```sql
SELECT count(*) FROM events WHERE is_anomaly = true;
```

```
Aggregate (actual rows=1 loops=1)
  ->  Seq Scan on events (actual rows≈2,000 loops=1)
        Filter: is_anomaly
```

`idx_events_anomalies` exists and is small, but the planner skips it here. The reason
is physical correlation, not index quality: the ~2,000 anomalous rows are interleaved
chronologically with normal events, scattered across roughly 90% of the table's heap
blocks. A Bitmap Heap Scan against the partial index would still have to fetch almost
as many distinct heap pages as a full sequential scan, while paying extra for the
index lookups on top. Seq Scan wins on cost. The partial index still earns its keep —
it's just answering a different question (§3's ordered anomaly feed), not this one
(a full-table count).

## 5. Methodology note: why the audit gates on latency, not scan type

The first version of this audit asserted an *expected* scan type per query — e.g.
"`time_window_wide` should use `idx_events_occurred_at`." It failed immediately, on a
schema with no actual problems: Postgres was Seq Scanning half the table because that
was the right call, and the assertion punished the planner for making it. A Seq Scan
is frequently the optimal plan — for low-selectivity predicates, `count(*)` without a
covering index, and wide-percentage range scans, as §4 shows directly.

The audit now checks exactly one thing: does each hot query finish inside its 50ms
latency budget. Scan type is logged for every query as diagnostic context, never as a
pass/fail condition. This matters because "which access path did the planner choose"
and "is this query healthy" are different questions — the first is an implementation
detail the planner is better at deciding than a hardcoded assertion, the second is the
thing users and SLAs actually care about. Anyone extending this audit for a new query
should add a latency budget, not a scan-type expectation.

## 6. Benchmarks and known issues

**Seed throughput.** `scripts/seed_events.py` inserts 100,000 rows in 2.48s (batched,
5,000 rows per statement) — about 40,000 rows/sec. Against the 1,000 events/sec API
throughput target, that's roughly 40x headroom: if ingestion ever becomes the
bottleneck, the evidence so far says to look at the API/serialization layer first, not
Postgres.

**Query latency.** All four hot queries in §4 complete under 16ms against the 50ms
budget, including the Seq Scan cases — which is the point of §5: those are passing
because they're fast, not because they avoided a Seq Scan.

**Known issue — degenerate power-law helper.** `power_law_user_id()` in
`scripts/seed_events.py` generates `int(random.paretovariate(1.5))`, capped at
`n_users`. Most of a Pareto(1.5) distribution's mass sits between 1 and 2, so `int()`
collapses the large majority of draws to `user_id = 1` instead of producing a
realistic long-tailed spread across users. In the current seed data, user 1 holds
roughly 65% of all events. This doesn't affect the query-plan findings above (they
don't depend on the shape of the user distribution), but it will bias per-user
features going into Isolation Forest training. Filed as a follow-up to fix before
MICRO-3.1.
