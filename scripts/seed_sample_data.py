"""Seed local Postgres with synthetic orders data.

Run after `make compose-up`. Inserts produce CDC events flowing to Kafka.
"""

from __future__ import annotations

import os
import random
import time
import uuid
from datetime import UTC, datetime

import psycopg2
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)


def _conn():
    return psycopg2.connect(
        host=os.environ.get("LOCAL_PG_HOST", "localhost"),
        port=int(os.environ.get("LOCAL_PG_PORT", "5432")),
        database=os.environ.get("LOCAL_PG_DATABASE", "analytics"),
        user=os.environ.get("LOCAL_PG_USER", "postgres"),
        password=os.environ.get("LOCAL_PG_PASSWORD", "postgres"),
    )


def seed_customers(n: int = 500) -> list[str]:
    """Seed customers table, return list of customer_ids."""
    ids: list[str] = []
    with _conn() as conn, conn.cursor() as cur:
        for _ in range(n):
            cid = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO public.customers (customer_id, name, email) VALUES (%s, %s, %s) "
                "ON CONFLICT (customer_id) DO NOTHING",
                (cid, fake.name(), fake.email()),
            )
            ids.append(cid)
        conn.commit()
    print(f"Seeded {len(ids)} customers")
    return ids


def seed_orders_stream(customer_ids: list[str], events_per_second: int = 5, duration_seconds: int = 300):
    """Continuously insert orders at ~events_per_second rate.

    Each INSERT is a CDC event flowing to the Kafka 'cdc.public.orders' topic.
    """
    interval = 1.0 / events_per_second
    start = datetime.now(UTC)
    total = 0

    with _conn() as conn, conn.cursor() as cur:
        while (datetime.now(UTC) - start).total_seconds() < duration_seconds:
            oid = str(uuid.uuid4())
            cid = random.choice(customer_ids)
            qty = random.randint(1, 5)
            amount = round(random.uniform(10, 500), 2)
            currency = random.choice(["USD", "EUR", "GBP", "JPY"])

            cur.execute(
                "INSERT INTO public.orders "
                "(order_id, customer_id, product_id, qty, total_amount, currency, order_ts) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (oid, cid, str(uuid.uuid4()), qty, amount, currency,
                 datetime.now(UTC)),
            )
            conn.commit()
            total += 1

            if total % 10 == 0:
                elapsed = (datetime.now(UTC) - start).total_seconds()
                rate = total / elapsed if elapsed > 0 else 0
                print(f"  Inserted {total:>6} orders, rate: {rate:.1f}/sec")

            time.sleep(interval)

    print(f"\nDone. Inserted {total} orders over {duration_seconds}s.")


def main() -> None:
    customer_ids = seed_customers()
    if not customer_ids:
        print("No customers available (already seeded?). Using dummy IDs.")
        customer_ids = [str(uuid.uuid4()) for _ in range(100)]
    seed_orders_stream(customer_ids, events_per_second=5, duration_seconds=60)


if __name__ == "__main__":
    main()
