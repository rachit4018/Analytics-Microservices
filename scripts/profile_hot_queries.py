"""EXPLAIN ANALYZE audit — MICRO-1.2d.

Runs the hot queries, prints each plan, and reports PASS/FAIL.

Key idea (the whole lesson of this ticket):
  A query is healthy if it meets its LATENCY budget.
  Which scan type the planner chose is context, NOT pass/fail.
  A Seq Scan can be the OPTIMAL plan (low selectivity, count(*),
  half-the-table range scans). So we never fail on scan type.

Run:  python scripts/explain_queries.py
Tip:  run `VACUUM ANALYZE events;` first for stable, realistic plans.
"""

import asyncio
import os
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/analytics"
)

MAX_LATENCY_MS = 50.0

HOT_QUERIES = {
    "recent_anomalies": "SELECT count(*) FROM events WHERE is_anomaly = true;",
    "per_user_history": """
        SELECT id, event_type, occurred_at, amount
        FROM events
        WHERE user_id = :user_id
        ORDER BY occurred_at DESC
        LIMIT 20;
    """,
    "time_window_wide": """
        SELECT event_type, COUNT(*), AVG(amount)
        FROM events
        WHERE occurred_at >= :wide_start AND occurred_at <= :wide_end
        GROUP BY event_type;
    """,
    "time_window_narrow": """
        SELECT event_type, COUNT(*), AVG(amount)
        FROM events
        WHERE occurred_at >= :narrow_start AND occurred_at <= :narrow_end
        GROUP BY event_type;
    """,
}


def classify_scan(plan_text: str) -> str:
    """Return a human label for the access path. Informational only."""
    if "Index Only Scan" in plan_text:
        return "Index Only Scan (best case — heap skipped)"
    if "Bitmap Index Scan" in plan_text:
        return "Bitmap Index Scan (index used, many matches)"
    if "Index Scan" in plan_text:
        return "Index Scan (index used)"
    if "Seq Scan" in plan_text:
        return "Seq Scan (full table — often optimal for low selectivity)"
    return "Other (aggregate/hash node on top)"


async def run_performance_audit() -> None:
    engine = create_async_engine(DATABASE_URL)

    async with engine.connect() as conn:
        # Pick a heavy user so per_user_history has rows to return.
        busiest = await conn.execute(text(
            "SELECT user_id FROM events GROUP BY user_id "
            "ORDER BY count(*) DESC LIMIT 1;"
        ))
        user_row = busiest.fetchone()
        if user_row is None:
            print("Error: events table is empty. Run the seed script first.")
            await engine.dispose()
            return

        bounds = await conn.execute(text(
            "SELECT min(occurred_at) AS min_t, max(occurred_at) AS max_t FROM events;"
        ))
        min_t, max_t = bounds.fetchone()

        params = {
            "user_id": user_row[0],
            # wide window = ~half the range -> planner should Seq Scan (correct!)
            "wide_start": min_t,
            "wide_end": min_t + (max_t - min_t) / 2,
            # narrow window = last 1 day -> selective -> index becomes worthwhile
            "narrow_start": max_t - __import__("datetime").timedelta(days=1),
            "narrow_end": max_t,
        }

        all_passed = True

        for name, raw_sql in HOT_QUERIES.items():
            print(f"\nEvaluating: [{name.upper()}]")
            print("-" * 60)

            result = await conn.execute(
                text(f"EXPLAIN (ANALYZE, BUFFERS) {raw_sql}"), params
            )
            plan_lines = [r[0] for r in result.fetchall()]
            plan_text = "\n".join(plan_lines)

            # --- Access path: INFORMATIONAL, never fails the audit ---
            print(f"  Access path : {classify_scan(plan_text)}")

            # --- Latency: THIS is the pass/fail gate ---
            m = re.search(r"Execution Time:\s+([\d.]+)\s+ms", plan_text)
            if m:
                exec_ms = float(m.group(1))
                if exec_ms < MAX_LATENCY_MS:
                    print(f"  Latency     : {exec_ms:.3f} ms  (PASS, < {MAX_LATENCY_MS} ms)")
                else:
                    print(f"  Latency     : {exec_ms:.3f} ms  (FAIL, >= {MAX_LATENCY_MS} ms)")
                    all_passed = False
            else:
                print("  Latency     : could not parse Execution Time")
                all_passed = False

            print("  Plan:")
            for line in plan_lines:
                print(f"    {line}")

        print("\n" + "=" * 60)
        print("AUDIT PASSED — all hot queries within latency budget"
              if all_passed else
              "AUDIT FAILED — a query exceeded the latency budget")
        print("=" * 60)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_performance_audit())