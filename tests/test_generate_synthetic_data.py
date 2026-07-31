"""Unit tests for the synthetic data generator.

These test the generator's own internal consistency (referential
integrity, reproducibility, arithmetic invariants) — not the database.
No Postgres connection is required.
"""

from __future__ import annotations

import random
from collections import defaultdict
from decimal import Decimal

import pandas as pd
from faker import Faker

from scripts.generate_synthetic_data import (
    SEED,
    _line_amount,
    generate_customers,
    generate_order_items,
    generate_orders,
    generate_payments,
    generate_products,
)


def _generate_all() -> dict[str, pd.DataFrame]:
    random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    customers = generate_customers(fake)
    products = generate_products(fake)
    orders = generate_orders(fake, customers)
    order_items = generate_order_items(orders, products)
    payments = generate_payments(fake, orders, order_items)
    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "order_items": order_items,
        "payments": payments,
    }


def test_generation_is_deterministic():
    first = _generate_all()
    second = _generate_all()
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name])


def test_primary_keys_are_unique():
    data = _generate_all()
    assert data["customers"]["customer_id"].is_unique
    assert data["products"]["product_id"].is_unique
    assert data["orders"]["order_id"].is_unique
    assert data["order_items"]["order_item_id"].is_unique
    assert data["payments"]["payment_id"].is_unique


def test_order_items_reference_real_orders_and_products():
    data = _generate_all()
    order_ids = set(data["orders"]["order_id"])
    product_ids = set(data["products"]["product_id"])
    assert set(data["order_items"]["order_id"]).issubset(order_ids)
    assert set(data["order_items"]["product_id"]).issubset(product_ids)


def test_order_items_only_reference_active_products():
    data = _generate_all()
    active_product_ids = set(data["products"].loc[data["products"]["is_active"], "product_id"])
    assert set(data["order_items"]["product_id"]).issubset(active_product_ids)


def test_orders_reference_real_customers():
    data = _generate_all()
    customer_ids = set(data["customers"]["customer_id"])
    assert set(data["orders"]["customer_id"]).issubset(customer_ids)


def test_payments_reference_real_orders_one_to_one():
    data = _generate_all()
    order_ids = set(data["orders"]["order_id"])
    assert set(data["payments"]["order_id"]).issubset(order_ids)
    assert len(data["payments"]) == len(data["orders"])


def test_payment_amount_matches_order_items_total():
    # Uses the same Decimal-based _line_amount() the generator itself uses,
    # rather than re-deriving the sum with plain floats — float summation
    # isn't associative, so a second float-based computation can land a
    # cent away from the generator's own result even when correct. This
    # guards against a regression back to float accumulation, which used
    # to disagree with the warehouse's own sum(line_amount) by a cent.
    data = _generate_all()
    order_items = data["order_items"]

    expected_totals: defaultdict[int, Decimal] = defaultdict(Decimal)
    for item in order_items.to_dict("records"):
        expected_totals[int(item["order_id"])] += _line_amount(
            item["quantity"], item["unit_price"], item["discount"]
        )

    payments_by_order = data["payments"].set_index("order_id")["amount"]

    for order_id, expected_amount in expected_totals.items():
        assert payments_by_order.loc[order_id] == float(expected_amount)


def test_no_negative_amounts():
    data = _generate_all()
    assert (data["order_items"]["unit_price"] >= 0).all()
    assert (data["order_items"]["quantity"] > 0).all()
    assert (data["payments"]["amount"] >= 0).all()
    assert (data["products"]["unit_cost"] >= 0).all()


def test_order_date_never_precedes_customer_signup():
    data = _generate_all()
    merged = data["orders"].merge(data["customers"], on="customer_id", suffixes=("_order", "_cust"))
    assert (merged["order_date"] >= merged["signup_date"]).all()
