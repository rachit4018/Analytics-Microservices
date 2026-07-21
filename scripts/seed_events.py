"""Seed script — MICRO-1.2c.

Generates ~100k realistic events with ~2% labeled anomalies.
Run:   python scripts/seed_events.py [--keep]
Tests: pytest tests/test_schema.py -k seed

Constraints (from ticket AC):
  - 100k rows in < 60s  -> bulk insert in batches of 5000, NOT row-by-row
  - ~2% anomalies: amount 50-100x normal, odd hours (00:00-04:00)
  - user_ids power-law distributed (helper provided below)
"""

import argparse
import asyncio
import os
import math
import random
from datetime import datetime, timedelta, timezone

from faker import Faker
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text, insert
# NOTE: import your finished models — 1.2a must be done first
from src.models.database import Event # noqa

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/analytics"
)

TOTAL_EVENTS = 100_000
BATCH_SIZE = 5_000
ANOMALY_RATE = 0.02
EVENT_TYPES = ["purchase", "trade", "claim", "refund", "transfer"]

fake = Faker()
def get_random_past_date(now: datetime) -> datetime:
    # 1. Define the maximum window size in seconds (30 days)
    # 30 days * 24 hours * 60 minutes * 60 seconds = 2,592,000 seconds
    max_seconds = 30 * 24 * 60 * 60
    
    # 2. Pick a uniformly random number of seconds within that range
    random_seconds = random.randint(0, max_seconds)
    
    # 3. Calculate 'now' using aware UTC (matches your TIMESTAMPTZ requirement)
    
    # 4. Subtract the random offset from 'now'
    return now - timedelta(seconds=random_seconds)

def get_random_forced_time_past_date(now: datetime) -> datetime:
    
    random_days_ago = random.randint(0, 30)
    
    # 2. Define your target daily hour window (00:00 to 04:00 is a 4-hour span)
    # 4 hours * 60 minutes * 60 seconds = 14,400 max seconds
    max_window_seconds = 4 * 60 * 60
    random_seconds_in_window = random.randint(0, max_window_seconds)
    
    # 3. Get *today's date* stripped down to midnight (00:00:00) in UTC
    # This acts as our precise baseline anchor point
    midnight_today = now.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    
    # 4. Step backward by the random number of days
    target_day = midnight_today - timedelta(days=random_days_ago)
    
    # 5. Step forward by the random seconds within your 00:00-04:00 window
    final_timestamp = target_day + timedelta(seconds=random_seconds_in_window)
    
    return final_timestamp

# Helper Function for the Power Law (Light and Heavy User id generation)
def power_law_user_id(n_users: int = 5_000) -> int:
    """Few heavy users, many light users. Provided — just call it."""
    return min(int(random.paretovariate(1.5)), n_users)


def make_normal_event(now: datetime) -> dict:
    """Build ONE normal event as a dict matching the events table columns.

    TODO(dev): return a dict with keys:
      event_type   -> random.choice(EVENT_TYPES)
      user_id      -> power_law_user_id()
      amount       -> plausible: e.g. round(random.lognormvariate(3, 1), 2)
      payload      -> small dict, e.g. {"channel": fake.random_element(("web","mobile","api"))}
      occurred_at  -> uniformly random within the last 30 days of `now`
      is_anomaly   -> False
      anomaly_score-> None
    """
    event  = {
            "event_type": random.choice(EVENT_TYPES),
            "user_id": power_law_user_id(),
            "amount": round(random.lognormvariate(3,1),2), # mu, sigma 
            "payload": {"channel": fake.random_element(("web","mobile","api"))},
            "occurred_at": get_random_past_date(now),
            "is_anomaly": False,
            "anomaly_score": None,
        }
    return event

def make_anomalous_event(now: datetime) -> dict:
    """Build ONE anomalous event.

    TODO(dev): like normal, EXCEPT:
      amount      -> 50-100x a normal amount
      occurred_at -> forced into 00:00-04:00 window on a random recent day
      is_anomaly  -> True   (this is our LABEL for MICRO-3.1 model eval)
    """
    baseline_mu = 3.0
    baseline_sigma = 1.0
    scale_factor = 90.0 # change the scale of value from here 
    scaled_mu = baseline_mu + math.log(scale_factor)
    

    event = {
            "event_type": random.choice(EVENT_TYPES),
            "user_id": power_law_user_id(),
            "amount": round(random.lognormvariate(scaled_mu,baseline_sigma),2),
            "payload": {"channel": fake.random_element(("web","mobile","api"))},
            "occurred_at": get_random_forced_time_past_date(now),
            "is_anomaly": True,
            "anomaly_score": None,
        }
    return event


async def seed(keep_existing: bool) -> None:
    engine = create_async_engine(DATABASE_URL)
    now = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        if not keep_existing:
            # TODO(dev): TRUNCATE events RESTART IDENTITY (use sqlalchemy text())
            await conn.execute(text("TRUNCATE TABLE events RESTART IDENTITY CASCADE"))


        inserted = 0
        while inserted < TOTAL_EVENTS:
            batch = []
            for _ in range(min(BATCH_SIZE, TOTAL_EVENTS - inserted)):
                # TODO(dev): with probability ANOMALY_RATE make an anomalous
                #            event, otherwise a normal one; append to batch
                
                if random.random()<ANOMALY_RATE :
                    event = make_anomalous_event(now)
                else:
                    event = make_normal_event(now)
                
                if event:
                    batch.append(event)
                else:
                    print("Error : Failed to create event")
                    raise ValueError

            # TODO(dev): bulk insert `batch` in ONE statement:
            #   await conn.execute(insert(Event), batch)
            # (insert comes from sqlalchemy — this is the <60s trick)
            await conn.execute(insert(Event),batch)
            inserted += len(batch)
            print(f"inserted {inserted}/{TOTAL_EVENTS}", end="\r")

    await engine.dispose()
    print(f"\ndone: {TOTAL_EVENTS} events seeded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="don't truncate first")
    args = parser.parse_args()
    asyncio.run(seed(keep_existing=args.keep))
