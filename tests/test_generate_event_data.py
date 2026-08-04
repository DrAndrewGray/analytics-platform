"""Unit tests for the product-event generator.

Like the billing generator's tests, these assert on the ten named
scenarios (customer_ids 11-20) by ID rather than only checking aggregate
properties — that's what actually catches a regression in identity
resolution or session-boundary logic.
"""

from __future__ import annotations

import random
from typing import cast

import pandas as pd
import pytest
from faker import Faker

from scripts.generate_event_data import build_dataset
from scripts.generate_synthetic_data import SEED as PHASE1_SEED
from scripts.generate_synthetic_data import (
    generate_customers,
    generate_order_items,
    generate_orders,
    generate_products,
)


@pytest.fixture(scope="module")
def phase1_data() -> dict[str, pd.DataFrame]:
    random.seed(PHASE1_SEED)
    fake = Faker()
    Faker.seed(PHASE1_SEED)
    customers = generate_customers(fake)
    products = generate_products(fake)
    orders = generate_orders(fake, customers)
    generate_order_items(orders, products)  # not used here, but keeps parity with main()
    return {"customers": customers, "products": products, "orders": orders}


@pytest.fixture(scope="module")
def events(phase1_data) -> pd.DataFrame:
    return build_dataset(phase1_data["customers"], phase1_data["products"], phase1_data["orders"])


def test_build_dataset_is_deterministic(phase1_data):
    first = build_dataset(phase1_data["customers"], phase1_data["products"], phase1_data["orders"])
    second = build_dataset(phase1_data["customers"], phase1_data["products"], phase1_data["orders"])
    pd.testing.assert_frame_equal(first, second)


def test_event_ids_are_unique(events):
    assert events["event_id"].is_unique


def test_referential_integrity(events, phase1_data):
    customer_ids = set(phase1_data["customers"]["customer_id"])
    product_ids = set(phase1_data["products"]["product_id"])
    order_ids = set(phase1_data["orders"]["order_id"])

    assert set(events["customer_id"].dropna()).issubset(customer_ids)
    assert set(events["product_id"].dropna()).issubset(product_ids)
    assert set(events["order_id"].dropna()).issubset(order_ids)


def test_every_anonymous_id_has_at_least_one_event(events):
    assert events.groupby("anonymous_id").size().min() >= 1


def _rows_for_customer(events: pd.DataFrame, customer_id: int) -> pd.DataFrame:
    subset = cast(pd.DataFrame, events[events["customer_id"] == customer_id])
    return subset.sort_values("event_id")


def test_scenario_11_pre_signup_events_share_anonymous_id_with_signup(events):
    signup = events[(events["customer_id"] == 11) & (events["event_type"] == "signup")].iloc[0]
    anon_id = signup["anonymous_id"]
    pre_signup = events[
        (events["anonymous_id"] == anon_id) & (events["event_id"] < signup["event_id"])
    ]
    assert len(pre_signup) == 2
    assert pre_signup["customer_id"].isna().all()


def test_scenario_12_never_identified(events):
    anon_id = events[events["event_id"] == 7]["anonymous_id"].iloc[0]
    rows = events[events["anonymous_id"] == anon_id]
    assert rows["customer_id"].isna().all()
    assert set(rows["event_type"]) == {"product_view", "add_to_cart"}
    assert "purchase" not in set(rows["event_type"])


def test_scenario_13_has_an_exact_duplicate(events):
    rows = _rows_for_customer(events, 13)
    assert len(rows) == 2
    assert rows["event_timestamp"].nunique() == 1
    assert rows["event_type"].nunique() == 1
    assert rows["product_id"].nunique() == 1


def test_scenario_14_has_a_gap_over_30_minutes(events):
    rows = _rows_for_customer(events, 14).sort_values("event_timestamp")
    gaps = rows["event_timestamp"].apply(pd.Timestamp).diff().dropna()
    assert (gaps > pd.Timedelta(minutes=30)).any()


def test_scenario_15_full_funnel_with_search(events):
    rows = _rows_for_customer(events, 15).sort_values("event_id")
    assert list(rows["event_type"]) == [
        "search",
        "product_view",
        "add_to_cart",
        "checkout_start",
        "purchase",
    ]
    assert rows.iloc[-1]["order_id"] == rows.iloc[-1]["order_id"]  # not null, see below
    assert pd.notna(rows.iloc[-1]["order_id"])


def test_scenario_16_identified_from_first_event(events):
    rows = _rows_for_customer(events, 16).sort_values("event_id")
    assert rows.iloc[0]["event_type"] == "login"
    assert bool(rows["customer_id"].notna().all())


def test_scenario_17_two_anonymous_ids_resolve_to_same_customer(events):
    rows = _rows_for_customer(events, 17)
    assert rows["anonymous_id"].nunique() == 2


def test_scenario_18_late_arriving_event_is_out_of_row_order(events):
    rows = _rows_for_customer(events, 18).sort_values("event_id")
    # The later row (by event_id) has an earlier timestamp than the row before it.
    timestamps = pd.to_datetime(rows["event_timestamp"]).tolist()
    assert timestamps[1] < timestamps[0]


def test_scenario_19_and_20_activation_window(events):
    fast = _rows_for_customer(events, 19)
    slow = _rows_for_customer(events, 20)

    fast_signup = pd.Timestamp(fast[fast["event_type"] == "signup"].iloc[0]["event_timestamp"])
    fast_purchase = pd.Timestamp(fast[fast["event_type"] == "purchase"].iloc[0]["event_timestamp"])
    assert (fast_purchase - fast_signup) <= pd.Timedelta(days=14)

    slow_signup = pd.Timestamp(slow[slow["event_type"] == "signup"].iloc[0]["event_timestamp"])
    slow_purchase = pd.Timestamp(slow[slow["event_type"] == "purchase"].iloc[0]["event_timestamp"])
    assert (slow_purchase - slow_signup) > pd.Timedelta(days=14)
