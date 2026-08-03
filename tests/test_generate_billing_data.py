"""Unit tests for the billing data generator.

Tests both general invariants (referential integrity, invoice-line
reconciliation, determinism) and the specific named scenarios — the
generator deliberately hand-crafts customers 1-10 to exercise one piece
of business logic each, so these tests assert on those customers by id
rather than only checking aggregate properties.
"""

from __future__ import annotations

import random

import pandas as pd
import pytest
from faker import Faker

from scripts.generate_billing_data import SEED, build_dataset
from scripts.generate_synthetic_data import SEED as PHASE1_SEED
from scripts.generate_synthetic_data import generate_customers


@pytest.fixture(scope="module")
def customers() -> pd.DataFrame:
    random.seed(PHASE1_SEED)
    fake = Faker()
    Faker.seed(PHASE1_SEED)
    return generate_customers(fake)


@pytest.fixture(scope="module")
def data(customers: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return build_dataset(customers)


def test_build_dataset_is_deterministic(customers):
    first = build_dataset(customers, seed=SEED)
    second = build_dataset(customers, seed=SEED)
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name])


def test_primary_keys_are_unique(data):
    assert data["plans"]["plan_id"].is_unique
    assert data["subscriptions"]["subscription_id"].is_unique
    assert data["invoices"]["invoice_id"].is_unique
    assert data["invoice_lines"]["invoice_line_id"].is_unique
    assert data["payments"]["payment_id"].is_unique
    assert data["refunds"]["refund_id"].is_unique


def test_referential_integrity(data, customers):
    customer_ids = set(customers["customer_id"])
    plan_ids = set(data["plans"]["plan_id"])
    subscription_ids = set(data["subscriptions"]["subscription_id"])
    invoice_ids = set(data["invoices"]["invoice_id"])
    payment_ids = set(data["payments"]["payment_id"])

    assert set(data["subscriptions"]["customer_id"]).issubset(customer_ids)
    assert set(data["subscriptions"]["plan_id"]).issubset(plan_ids)
    assert set(data["invoices"]["subscription_id"]).issubset(subscription_ids)
    assert set(data["invoices"]["customer_id"]).issubset(customer_ids)
    assert set(data["invoice_lines"]["invoice_id"]).issubset(invoice_ids)
    assert set(data["payments"]["invoice_id"]).issubset(invoice_ids)
    assert set(data["refunds"]["payment_id"]).issubset(payment_ids)


def test_trial_phases_are_never_invoiced(data):
    trial_subscription_ids = set(
        data["subscriptions"].loc[data["subscriptions"]["is_trial"], "subscription_id"]
    )
    assert not trial_subscription_ids & set(data["invoices"]["subscription_id"])


def test_invoice_lines_sum_to_invoice_amount(data):
    line_totals = data["invoice_lines"].groupby("invoice_id")["amount"].sum().round(2)
    invoice_amounts = data["invoices"].set_index("invoice_id")["amount"]
    for invoice_id, total in line_totals.items():
        assert total == invoice_amounts.loc[invoice_id], f"invoice {invoice_id} line mismatch"


def test_refunds_never_exceed_their_payment(data):
    payments_by_id = data["payments"].set_index("payment_id")["amount"]
    for _, refund in data["refunds"].iterrows():
        assert refund["amount"] <= payments_by_id.loc[refund["payment_id"]] + 1e-9


def test_no_negative_amounts(data):
    assert (data["invoices"]["amount"] >= 0).all()
    assert (data["invoice_lines"]["amount"] >= 0).all()
    assert (data["payments"]["amount"] >= 0).all()
    assert (data["refunds"]["amount"] >= 0).all()


# --- Named scenarios (customers 1-10) -------------------------------------


def test_scenario_1_new_monthly_subscriber_no_changes(data):
    subs = data["subscriptions"]
    rows = subs[subs["customer_id"] == 1]
    assert len(rows) == 1
    assert rows.iloc[0]["plan_id"] == 1
    assert pd.isna(rows.iloc[0]["phase_end_date"])


def test_scenario_3_trial_converts_to_paid(data):
    rows = data["subscriptions"][data["subscriptions"]["customer_id"] == 3].sort_values(
        "subscription_id"
    )
    assert len(rows) == 2
    assert rows.iloc[0]["is_trial"]
    assert rows.iloc[0]["ended_reason"] == "upgraded"
    assert not rows.iloc[1]["is_trial"]
    assert rows.iloc[0]["phase_end_date"] == rows.iloc[1]["phase_start_date"]


def test_scenario_4_upgrade_changes_plan(data):
    rows = data["subscriptions"][data["subscriptions"]["customer_id"] == 4].sort_values(
        "subscription_id"
    )
    assert len(rows) == 2
    assert rows.iloc[0]["plan_id"] == 1  # Basic Monthly
    assert rows.iloc[1]["plan_id"] == 3  # Pro Monthly
    assert rows.iloc[1]["phase_type"] == "upgrade"


def test_scenario_5_downgrade_changes_plan(data):
    rows = data["subscriptions"][data["subscriptions"]["customer_id"] == 5].sort_values(
        "subscription_id"
    )
    assert len(rows) == 2
    assert rows.iloc[0]["plan_id"] == 3  # Pro Monthly
    assert rows.iloc[1]["plan_id"] == 1  # Basic Monthly
    assert rows.iloc[1]["phase_type"] == "downgrade"


def test_scenario_6_cancelled_then_never_returns(data):
    rows = data["subscriptions"][data["subscriptions"]["customer_id"] == 6]
    assert len(rows) == 1
    assert rows.iloc[0]["ended_reason"] == "cancelled"


def test_scenario_6_last_invoice_has_failed_then_retry_payment(data):
    invoices = data["invoices"]
    cust_invoices = invoices[invoices["customer_id"] == 6].sort_values("invoice_id")
    last_invoice_id = cust_invoices.iloc[-1]["invoice_id"]
    payments = data["payments"][data["payments"]["invoice_id"] == last_invoice_id]
    assert len(payments) == 2
    assert set(payments["status"]) == {"failed", "succeeded"}
    assert payments[payments["status"] == "succeeded"].iloc[0]["is_retry"]


def test_scenario_7_cancelled_then_reactivated_with_gap(data):
    rows = data["subscriptions"][data["subscriptions"]["customer_id"] == 7].sort_values(
        "subscription_id"
    )
    assert len(rows) == 2
    assert rows.iloc[0]["ended_reason"] == "cancelled"
    assert rows.iloc[1]["phase_type"] == "reactivation"
    gap_days = (
        pd.Timestamp(rows.iloc[1]["phase_start_date"])
        - pd.Timestamp(rows.iloc[0]["phase_end_date"])
    ).days
    assert gap_days >= 30


def test_scenario_7_first_payment_fully_refunded(data):
    invoices = data["invoices"][data["invoices"]["customer_id"] == 7].sort_values("invoice_id")
    first_invoice_id = invoices.iloc[0]["invoice_id"]
    payment = data["payments"][data["payments"]["invoice_id"] == first_invoice_id].iloc[0]
    refund = data["refunds"][data["refunds"]["payment_id"] == payment["payment_id"]]
    assert len(refund) == 1
    assert refund.iloc[0]["amount"] == payment["amount"]


def test_scenario_8_paused_then_reactivated(data):
    rows = data["subscriptions"][data["subscriptions"]["customer_id"] == 8].sort_values(
        "subscription_id"
    )
    assert len(rows) == 2
    assert rows.iloc[0]["ended_reason"] == "paused"
    assert rows.iloc[1]["phase_type"] == "reactivation"


def test_scenario_8_first_payment_partially_refunded(data):
    invoices = data["invoices"][data["invoices"]["customer_id"] == 8].sort_values("invoice_id")
    first_invoice_id = invoices.iloc[0]["invoice_id"]
    payment = data["payments"][data["payments"]["invoice_id"] == first_invoice_id].iloc[0]
    refund = data["refunds"][data["refunds"]["payment_id"] == payment["payment_id"]]
    assert len(refund) == 1
    assert 0 < refund.iloc[0]["amount"] < payment["amount"]


def test_scenario_9_annual_plan_invoices_a_year_apart(data):
    rows = data["invoices"][data["invoices"]["customer_id"] == 9].sort_values("invoice_id")
    assert len(rows) == 2
    gap_days = (
        pd.Timestamp(rows.iloc[1]["invoice_date"]) - pd.Timestamp(rows.iloc[0]["invoice_date"])
    ).days
    assert 360 <= gap_days <= 370


def test_scenario_9_first_invoice_partially_paid(data):
    invoices = data["invoices"][data["invoices"]["customer_id"] == 9].sort_values("invoice_id")
    first_invoice = invoices.iloc[0]
    payment = data["payments"][data["payments"]["invoice_id"] == first_invoice["invoice_id"]].iloc[
        0
    ]
    assert 0 < payment["amount"] < first_invoice["amount"]


def test_scenario_10_first_invoice_has_two_lines(data):
    invoices = data["invoices"][data["invoices"]["customer_id"] == 10].sort_values("invoice_id")
    first_invoice_id = invoices.iloc[0]["invoice_id"]
    lines = data["invoice_lines"][data["invoice_lines"]["invoice_id"] == first_invoice_id]
    assert len(lines) == 2


def test_scenario_10_one_invoice_unpaid_one_invoice_late(data):
    invoices = data["invoices"][data["invoices"]["customer_id"] == 10].sort_values("invoice_id")
    second_invoice_id = invoices.iloc[1]["invoice_id"]
    third_invoice_id = invoices.iloc[2]["invoice_id"]

    second_payments = data["payments"][data["payments"]["invoice_id"] == second_invoice_id]
    assert (second_payments["status"] == "failed").all()

    third_invoice_date = pd.Timestamp(invoices.iloc[2]["invoice_date"])
    third_payment = data["payments"][data["payments"]["invoice_id"] == third_invoice_id].iloc[0]
    lag_days = (pd.Timestamp(third_payment["payment_date"]) - third_invoice_date).days
    assert lag_days >= 30
