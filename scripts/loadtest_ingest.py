"""Load test for POST /events — MICRO-2.1 T5.

Goal: confirm the endpoint sustains the 1000 events/sec target and report
throughput. This is your baseline vs the 40k rows/sec RAW insert number from
the seed script — the gap is what the HTTP + validation + session layer costs.

Run the app first:  TESTING=  uvicorn src.main:app --port 8000
Then:               python scripts/loadtest_ingest.py
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx

URL = "http://localhost:8000/events"
BATCHES = 20
EVENTS_PER_BATCH = 1000


def make_batch(n: int) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "events": [
            {
                "event_type": "purchase",
                "user_id": (i % 5000) + 1,
                "amount": "49.99",
                "payload": {"channel": "api"},
                "occurred_at": (now - timedelta(seconds=i)).isoformat(),
            }
            for i in range(n)
        ]
    }


async def send_batch(client: httpx.AsyncClient, payload: dict) -> int:
    response = await client.post(
        URL,
        json=payload,
        headers={
            "X-Request-ID": f"loadtest - {time.time_ns()}",
        },
    )
    response.raise_for_status()


# request_id, payload,
async def main() -> None:
    # TODO(dev) T5:
    #   - build a batch once (reuse it)
    #   - fire BATCHES requests, optionally concurrently (asyncio.gather)
    #   - measure total wall time
    #   - compute events/sec = (BATCHES * EVENTS_PER_BATCH) / elapsed
    #   - print throughput and compare to the 1000/sec target
    #
    # Suggested: run sequentially first (clean baseline), then try
    # concurrency=5 and see how throughput changes. Note it in your PR.

    payload = make_batch(EVENTS_PER_BATCH)

    async with httpx.AsyncClient(timeout=60.0) as client:
        start = time.perf_counter()
        # Sequential Logic
        for _ in range(BATCHES):
            await send_batch(client, payload)

        # Concurrency logic
        # concurrency = 5
        # for i in range(0, BATCHES, concurrency):
        #     tasks = [
        #         send_batch(client, payload)
        #         for _ in range(min(concurrency, BATCHES - i))
        #     ]
        #     await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start
    total_events = BATCHES * EVENTS_PER_BATCH
    throughput = total_events / elapsed
    print(f"Total events : {total_events}")
    print(f"Elapsed time : {elapsed:.2f} sec")
    print(f"Throughput   : {throughput:.2f} events/sec")

    if throughput >= 1000:
        print("✅ Target achieved (>=1000 events/sec)")
    else:
        print("❌ Target NOT achieved (<1000 events/sec)")


if __name__ == "__main__":
    asyncio.run(main())
