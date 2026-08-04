"""Generate synthetic raw data for the Meridian fictional retailer.

Produces CSVs under data/raw/ that stand in for extracts from a source
system: customers, products, orders, order_items, payments. A fixed seed
keeps the dataset reproducible across machines and CI runs.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

SEED = 20260731

# A fixed reference date, not real-world "today": Faker's relative date
# strings ("-3y", "today") resolve against the actual system clock at call
# time, which means the same seed produced different data depending on
# which real calendar day you ran this on — a genuine reproducibility bug
# that the "two calls in the same process" determinism test never caught,
# since both calls happened on the same day. Shared with the billing and
# event generators, which already anchor to this exact date.
TODAY = date(2026, 8, 2)

N_CUSTOMERS = 500
N_PRODUCTS = 40
N_ORDERS = 3000

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

CATEGORIES = ["Outdoor", "Apparel", "Footwear", "Accessories", "Home"]
CHANNELS = ["web", "mobile", "retail"]
ORDER_STATUSES_WEIGHTS = [("completed", 0.82), ("cancelled", 0.08), ("refunded", 0.10)]
PAYMENT_METHODS = ["card", "paypal", "gift_card", "bank_transfer"]
PAYMENT_STATUSES_WEIGHTS = [("succeeded", 0.90), ("failed", 0.06), ("refunded", 0.04)]


def weighted_choice(pairs: list[tuple[str, float]]) -> str:
    labels, weights = zip(*pairs, strict=True)
    return random.choices(labels, weights=weights, k=1)[0]


def generate_customers(fake: Faker) -> pd.DataFrame:
    rows = []
    for customer_id in range(1, N_CUSTOMERS + 1):
        signup_date = fake.date_between(
            start_date=TODAY - timedelta(days=3 * 365), end_date=TODAY - timedelta(days=30)
        )
        rows.append(
            {
                "customer_id": customer_id,
                "first_name": fake.first_name(),
                "last_name": fake.last_name(),
                "email": fake.unique.email(),
                "signup_date": signup_date,
                "region": fake.state(),
                "country": "United States",
            }
        )
    return pd.DataFrame(rows)


def generate_products(fake: Faker) -> pd.DataFrame:
    rows = []
    for product_id in range(1, N_PRODUCTS + 1):
        cost = round(random.uniform(5, 120), 2)
        margin = random.uniform(1.4, 2.8)
        rows.append(
            {
                "product_id": product_id,
                "product_name": fake.unique.catch_phrase(),
                "category": random.choice(CATEGORIES),
                "unit_cost": cost,
                "unit_price": round(cost * margin, 2),
                "is_active": random.random() > 0.05,
            }
        )
    return pd.DataFrame(rows)


def generate_orders(fake: Faker, customers: pd.DataFrame) -> pd.DataFrame:
    rows = []
    customer_ids = customers["customer_id"].tolist()
    signup_by_customer = dict(
        zip(customers["customer_id"], customers["signup_date"], strict=True)
    )
    for order_id in range(1, N_ORDERS + 1):
        customer_id = random.choice(customer_ids)
        earliest = signup_by_customer[customer_id]
        order_date = fake.date_between(start_date=earliest, end_date=TODAY)
        rows.append(
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "order_date": order_date,
                "status": weighted_choice(ORDER_STATUSES_WEIGHTS),
                "channel": random.choice(CHANNELS),
            }
        )
    return pd.DataFrame(rows)


def generate_order_items(orders: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    # DataFrame.sample() draws from numpy's RNG, not Python's `random` module.
    # An explicit local Generator keeps this deterministic under the same
    # SEED without depending on (or mutating) numpy's global random state.
    rng = np.random.default_rng(SEED)

    rows = []
    order_item_id = 1
    active_products = products[products["is_active"]]
    for _, order in orders.iterrows():
        n_items = random.randint(1, 4)
        chosen = active_products.sample(n=n_items, replace=True, random_state=rng)
        for _, product in chosen.iterrows():
            discount = round(random.choice([0, 0, 0, 0.1, 0.15, 0.2]), 2)
            rows.append(
                {
                    "order_item_id": order_item_id,
                    "order_id": order["order_id"],
                    "product_id": product["product_id"],
                    "quantity": random.randint(1, 3),
                    "unit_price": product["unit_price"],
                    "discount": discount,
                }
            )
            order_item_id += 1
    return pd.DataFrame(rows)


def _line_amount(quantity: int, unit_price: float, discount: float) -> Decimal:
    return (
        Decimal(quantity) * Decimal(str(unit_price)) * (Decimal("1") - Decimal(str(discount)))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generate_payments(fake: Faker, orders: pd.DataFrame, order_items: pd.DataFrame) -> pd.DataFrame:
    # A plain dict aggregation rather than groupby(): pandas' type stubs
    # resolve groupby(...)[col].sum() to an unusably broad union of scalar
    # types, which isn't worth fighting for a one-off rollup like this.
    #
    # Decimal, not float, for the rollup: float addition isn't associative,
    # so summing the same rounded-per-line amounts in a different order (a
    # Python loop here vs. Postgres' sum() in fct_orders) can land a cent
    # away even when every input is identical. Decimal addition is exact,
    # so this always agrees with the warehouse's own sum(line_amount).
    order_totals: defaultdict[int, Decimal] = defaultdict(Decimal)
    for item in order_items.to_dict("records"):
        order_totals[int(item["order_id"])] += _line_amount(
            item["quantity"], item["unit_price"], item["discount"]
        )

    rows = []
    payment_id = 1
    for order in orders.to_dict("records"):
        amount = float(order_totals.get(int(order["order_id"]), Decimal("0.00")))
        payment_date = order["order_date"] + timedelta(days=random.randint(0, 2))
        status = (
            "refunded"
            if order["status"] == "refunded"
            else weighted_choice(PAYMENT_STATUSES_WEIGHTS)
        )
        rows.append(
            {
                "payment_id": payment_id,
                "order_id": order["order_id"],
                "payment_date": payment_date,
                "amount": amount,
                "payment_method": random.choice(PAYMENT_METHODS),
                "status": status,
            }
        )
        payment_id += 1
    return pd.DataFrame(rows)


def main() -> None:
    random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    customers = generate_customers(fake)
    products = generate_products(fake)
    orders = generate_orders(fake, customers)
    order_items = generate_order_items(orders, products)
    payments = generate_payments(fake, orders, order_items)

    customers.to_csv(OUTPUT_DIR / "customers.csv", index=False)
    products.to_csv(OUTPUT_DIR / "products.csv", index=False)
    orders.to_csv(OUTPUT_DIR / "orders.csv", index=False)
    order_items.to_csv(OUTPUT_DIR / "order_items.csv", index=False)
    payments.to_csv(OUTPUT_DIR / "payments.csv", index=False)

    print(f"Wrote {len(customers)} customers, {len(products)} products, "
          f"{len(orders)} orders, {len(order_items)} order_items, "
          f"{len(payments)} payments to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
