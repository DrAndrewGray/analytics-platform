"""Generate synthetic clickstream/product-event data for Meridian's site.

Extends the Phase 1/2 dataset (customers, products, orders) with a
product-event domain: anonymous browsing, identity resolution when a
visitor signs up or logs in, and the funnel through to purchase (linked
to a real Phase 1 order where one exists).

Requires data/raw/customers.csv, products.csv, and orders.csv to already
exist (run generate_synthetic_data.py first).

Ten named scenarios (customer_ids 11-20, disjoint from Phase 2's 1-10)
each exercise one specific piece of logic — see
docs/metric_definitions_events.md. A larger randomized set covers other
customers for realistic volume.

Deliberately, no session_id column: sessionization is a downstream
transform (see docs/business_context_events.md), computed in dbt from
event_timestamp gaps, not trusted from an upstream source field.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pandas as pd

SEED = 20260804

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUTPUT_DIR = RAW_DIR / "events"
CUSTOMERS_CSV = RAW_DIR / "customers.csv"
PRODUCTS_CSV = RAW_DIR / "products.csv"
ORDERS_CSV = RAW_DIR / "orders.csv"

TODAY = datetime(2026, 8, 2, 12, 0, 0)

NAMED_SCENARIO_CUSTOMER_IDS = list(range(11, 21))

EVENT_TYPES = [
    "page_view",
    "search",
    "product_view",
    "add_to_cart",
    "remove_from_cart",
    "checkout_start",
    "purchase",
    "signup",
    "login",
]


def _new_anon_id(rng: random.Random) -> str:
    return "anon_" + uuid.UUID(int=rng.getrandbits(128), version=4).hex[:16]


class EventRow:
    __slots__ = (
        "anonymous_id",
        "customer_id",
        "event_type",
        "event_timestamp",
        "product_id",
        "order_id",
        "search_query",
    )

    def __init__(
        self,
        anonymous_id: str,
        event_type: str,
        event_timestamp: datetime,
        customer_id: int | None = None,
        product_id: int | None = None,
        order_id: int | None = None,
        search_query: str | None = None,
    ) -> None:
        self.anonymous_id = anonymous_id
        self.customer_id = customer_id
        self.event_type = event_type
        self.event_timestamp = event_timestamp
        self.product_id = product_id
        self.order_id = order_id
        self.search_query = search_query

    def to_dict(self) -> dict:
        return {
            "anonymous_id": self.anonymous_id,
            "customer_id": self.customer_id,
            "event_type": self.event_type,
            "event_timestamp": self.event_timestamp,
            "product_id": self.product_id,
            "order_id": self.order_id,
            "search_query": self.search_query,
        }


def _named_scenarios(
    products: pd.DataFrame, orders: pd.DataFrame, rng: random.Random
) -> list[EventRow]:
    product_ids = products["product_id"].tolist()
    rows: list[EventRow] = []

    def order_for(customer_id: int) -> int | None:
        cust_orders = orders[orders["customer_id"] == customer_id]
        if cust_orders.empty:
            return None
        return int(cust_orders.iloc[0]["order_id"])

    def scenario(anon: str, base: datetime):
        def add(minutes: int, event_type: str, **kwargs) -> None:
            rows.append(EventRow(anon, event_type, base + timedelta(minutes=minutes), **kwargs))

        return add

    # 11: anonymous browse -> signup -> purchase, one session, full funnel.
    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 1, 10, 0, 0))
    add(0, "product_view", product_id=product_ids[0])
    add(2, "product_view", product_id=product_ids[1])
    add(5, "signup", customer_id=11)
    add(6, "add_to_cart", customer_id=11, product_id=product_ids[1])
    add(8, "checkout_start", customer_id=11)
    add(9, "purchase", customer_id=11, order_id=order_for(11))

    # 12: fully anonymous, never identifies, abandons cart.
    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 2, 14, 0, 0))
    add(0, "product_view", product_id=product_ids[2])
    add(3, "add_to_cart", product_id=product_ids[2])

    # 13: exact duplicate event (double-fired beacon).
    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 3, 9, 0, 0))
    add(0, "product_view", customer_id=13, product_id=product_ids[3])
    add(0, "product_view", customer_id=13, product_id=product_ids[3])  # exact dup

    # 14: two sessions for the same anonymous_id (gap > 30 min).
    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 4, 8, 0, 0))
    add(0, "page_view", customer_id=14)
    add(5, "product_view", customer_id=14, product_id=product_ids[4])
    add(120, "page_view", customer_id=14)
    add(124, "product_view", customer_id=14, product_id=product_ids[5])

    # 15: search -> product_view -> add_to_cart -> checkout -> purchase.
    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 5, 11, 0, 0))
    add(0, "search", customer_id=15, search_query="waterproof jacket")
    add(1, "product_view", customer_id=15, product_id=product_ids[6])
    add(2, "add_to_cart", customer_id=15, product_id=product_ids[6])
    add(3, "checkout_start", customer_id=15)
    add(4, "purchase", customer_id=15, order_id=order_for(15))

    # 16: already-identified customer from the very first event (returning, logged in).
    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 6, 16, 0, 0))
    add(0, "login", customer_id=16)
    add(1, "product_view", customer_id=16, product_id=product_ids[7])

    # 17: two different anonymous_ids, both eventually resolving to customer 17.
    anon_a = _new_anon_id(rng)
    anon_b = _new_anon_id(rng)
    t = datetime(2026, 5, 7, 9, 0, 0)
    add_a = scenario(anon_a, t)
    add_b = scenario(anon_b, t + timedelta(days=1))
    add_a(0, "product_view", product_id=product_ids[8])
    add_a(2, "login", customer_id=17)
    add_b(0, "product_view", product_id=product_ids[9])
    add_b(1, "login", customer_id=17)

    # 18: late-arriving event — appears later in generation/row order but its
    # event_timestamp is earlier than a neighboring event already listed.
    # Resolution/sessionization logic must sort by event_timestamp, not
    # trust row order.
    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 8, 10, 0, 0))
    add(10, "product_view", customer_id=18, product_id=product_ids[0])
    add(0, "page_view", customer_id=18)  # out of order: earlier timestamp, later row

    # 19/20: activation pair — one fast (within 14 days), one slow (beyond 14 days).
    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 9, 10, 0, 0))
    add(0, "signup", customer_id=19)
    add(3 * 24 * 60, "purchase", customer_id=19, order_id=order_for(19))

    anon = _new_anon_id(rng)
    add = scenario(anon, datetime(2026, 5, 10, 10, 0, 0))
    add(0, "signup", customer_id=20)
    add(25 * 24 * 60, "purchase", customer_id=20, order_id=order_for(20))

    return rows


def _random_events(
    customers: pd.DataFrame,
    products: pd.DataFrame,
    orders: pd.DataFrame,
    rng: random.Random,
) -> list[EventRow]:
    product_ids = products["product_id"].tolist()
    other_customers = customers[~customers["customer_id"].isin(NAMED_SCENARIO_CUSTOMER_IDS)]
    sample_seed = rng.randint(0, 2**31 - 1)
    sample_size = min(150, len(other_customers))
    sampled = cast(pd.DataFrame, other_customers.sample(n=sample_size, random_state=sample_seed))

    orders_by_customer: dict[int, list[int]] = {}
    for order in orders.to_dict("records"):
        orders_by_customer.setdefault(int(order["customer_id"]), []).append(int(order["order_id"]))

    rows: list[EventRow] = []
    for customer in sampled.to_dict("records"):
        customer_id = int(customer["customer_id"])
        anon = _new_anon_id(rng)
        base = TODAY - timedelta(days=rng.randint(1, 200), hours=rng.randint(0, 23))

        rows.append(EventRow(anon, "page_view", base))
        n_views = rng.randint(1, 3)
        viewed_products = rng.sample(product_ids, k=min(n_views, len(product_ids)))
        for i, product_id in enumerate(viewed_products):
            view_time = base + timedelta(minutes=2 * (i + 1))
            rows.append(EventRow(anon, "product_view", view_time, product_id=product_id))

        customer_orders = orders_by_customer.get(customer_id, [])
        if customer_orders and rng.random() < 0.5:
            identify_event = rng.choice(["signup", "login"])
            identify_time = base + timedelta(minutes=10)
            rows.append(EventRow(anon, identify_event, identify_time, customer_id=customer_id))
            rows.append(
                EventRow(
                    anon,
                    "add_to_cart",
                    identify_time + timedelta(minutes=1),
                    customer_id=customer_id,
                    product_id=viewed_products[-1],
                )
            )
            checkout_time = identify_time + timedelta(minutes=2)
            rows.append(EventRow(anon, "checkout_start", checkout_time, customer_id=customer_id))
            rows.append(
                EventRow(
                    anon,
                    "purchase",
                    identify_time + timedelta(minutes=3),
                    customer_id=customer_id,
                    order_id=rng.choice(customer_orders),
                )
            )

    return rows


def build_dataset(
    customers: pd.DataFrame, products: pd.DataFrame, orders: pd.DataFrame, seed: int = SEED
) -> pd.DataFrame:
    rng = random.Random(seed)

    named = _named_scenarios(products, orders, rng)
    randomized = _random_events(customers, products, orders, rng)
    df = pd.DataFrame([r.to_dict() for r in named + randomized])
    df.insert(0, "event_id", range(1, len(df) + 1))
    return df


def main() -> None:
    for csv_path, name in [
        (CUSTOMERS_CSV, "generate_synthetic_data.py"),
        (PRODUCTS_CSV, "generate_synthetic_data.py"),
        (ORDERS_CSV, "generate_synthetic_data.py"),
    ]:
        if not csv_path.exists():
            raise FileNotFoundError(f"{csv_path} not found — run {name} first")

    customers = pd.read_csv(CUSTOMERS_CSV)
    products = pd.read_csv(PRODUCTS_CSV)
    orders = pd.read_csv(ORDERS_CSV)

    events = build_dataset(customers, products, orders)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events.to_csv(OUTPUT_DIR / "events.csv", index=False)
    print(f"Wrote {len(events)} events to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
