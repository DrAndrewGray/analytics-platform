"""Generate synthetic billing data for the Meridian+ membership program.

Extends the Phase 1 dataset (customers) with a subscription-billing
domain: plans, subscriptions, invoices, invoice_lines, payments, and
refunds. Produces CSVs under data/raw/ alongside the Phase 1 files.

Requires data/raw/customers.csv to already exist (run
generate_synthetic_data.py first) — subscriptions reference real
customers and must start on or after each customer's signup date.

Two kinds of subscriptions are generated:

- A small set of **named scenarios** (fixed customer_ids, fully
  deterministic dates and outcomes) that each exercise one specific
  piece of business logic — trial conversion, upgrade, downgrade,
  cancellation, reactivation, partial payment, full/partial refund,
  multi-line invoices, a late payment. These give the dbt tests
  something precise to assert against, not just aggregate sanity
  checks.
- A larger set of **randomized chains** across the remaining customers,
  for realistic volume and distribution.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

SEED = 20260802

# A separate subdirectory, not data/raw/ directly: the billing domain has
# its own `payments` table, which would otherwise silently overwrite the
# Phase 1 retail `payments.csv` (same filename, same directory, different
# schema) — this mirrors billing being a genuinely separate source system.
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUTPUT_DIR = RAW_DIR / "billing"
CUSTOMERS_CSV = RAW_DIR / "customers.csv"

TODAY = date(2026, 8, 2)

PLANS = [
    {
        "plan_id": 1,
        "plan_name": "Basic Monthly",
        "billing_interval": "monthly",
        "price": 9.99,
        "currency": "USD",
    },
    {
        "plan_id": 2,
        "plan_name": "Basic Annual",
        "billing_interval": "annual",
        "price": 99.00,
        "currency": "USD",
    },
    {
        "plan_id": 3,
        "plan_name": "Pro Monthly",
        "billing_interval": "monthly",
        "price": 19.99,
        "currency": "USD",
    },
    {
        "plan_id": 4,
        "plan_name": "Pro Annual",
        "billing_interval": "annual",
        "price": 199.00,
        "currency": "USD",
    },
]
PLANS_BY_ID = {p["plan_id"]: p for p in PLANS}

BASIC_MONTHLY, BASIC_ANNUAL, PRO_MONTHLY, PRO_ANNUAL = 1, 2, 3, 4

PAYMENT_METHODS = ["card", "paypal", "bank_transfer"]


def _months_later(d: date, n: int) -> date:
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, 28)  # avoid month-length edge cases; good enough for synthetic dates
    return date(year, month, day)


@dataclass
class PhaseSpec:
    plan_id: int
    start_date: date
    end_date: date | None  # None = still active
    phase_type: str  # 'trial' | 'new' | 'upgrade' | 'downgrade' | 'reactivation'
    is_trial: bool
    ended_reason: str | None  # 'cancelled' | 'paused' | 'upgraded' | 'downgraded' | None


@dataclass
class PaymentOutcome:
    """Scripted payment behavior for one invoice, used by named scenarios."""

    kind: str  # 'full', 'failed_then_retry', 'partial', 'unpaid', 'late'
    refund: str | None = None  # None | 'full' | 'partial'
    refund_delay_days: int = 20


# ---------------------------------------------------------------------------
# Named scenarios: customer_ids 1-10 (reserved; never used by random chains)
# ---------------------------------------------------------------------------

NAMED_SCENARIO_CUSTOMER_IDS = set(range(1, 11))


def _named_scenarios() -> dict[int, list[PhaseSpec]]:
    scenarios: dict[int, list[PhaseSpec]] = {}

    # 1: new monthly subscriber, still active, no changes ever.
    scenarios[1] = [
        PhaseSpec(BASIC_MONTHLY, date(2025, 1, 15), None, "new", False, None),
    ]

    # 2: new annual subscriber, still active — exercises annual -> MRR/12.
    scenarios[2] = [
        PhaseSpec(PRO_ANNUAL, date(2025, 2, 1), None, "new", False, None),
    ]

    # 3: trial, then converts to paid the same month it starts.
    scenarios[3] = [
        PhaseSpec(BASIC_MONTHLY, date(2025, 3, 1), date(2025, 3, 15), "trial", True, "upgraded"),
        PhaseSpec(BASIC_MONTHLY, date(2025, 3, 15), None, "new", False, None),
    ]

    # 4: upgrade mid-lifecycle (Basic Monthly -> Pro Monthly) — expansion MRR.
    scenarios[4] = [
        PhaseSpec(BASIC_MONTHLY, date(2025, 1, 1), date(2025, 6, 1), "new", False, "upgraded"),
        PhaseSpec(PRO_MONTHLY, date(2025, 6, 1), None, "upgrade", False, None),
    ]

    # 5: downgrade mid-lifecycle (Pro Monthly -> Basic Monthly) — contraction MRR.
    scenarios[5] = [
        PhaseSpec(PRO_MONTHLY, date(2025, 1, 1), date(2025, 7, 1), "new", False, "downgraded"),
        PhaseSpec(BASIC_MONTHLY, date(2025, 7, 1), None, "downgrade", False, None),
    ]

    # 6: cancels after a few months and never comes back — churned MRR.
    scenarios[6] = [
        PhaseSpec(BASIC_MONTHLY, date(2025, 1, 1), date(2025, 4, 1), "new", False, "cancelled"),
    ]

    # 7: cancels, then reactivates several months later — reactivation MRR,
    # distinct from new MRR despite both being "0 -> nonzero".
    scenarios[7] = [
        PhaseSpec(BASIC_MONTHLY, date(2025, 1, 1), date(2025, 3, 1), "new", False, "cancelled"),
        PhaseSpec(BASIC_MONTHLY, date(2025, 8, 1), None, "reactivation", False, None),
    ]

    # 8: pauses, then resumes — same reactivation mechanics as #7, via a
    # different ended_reason, to prove the classification doesn't hinge on
    # "cancelled" specifically.
    scenarios[8] = [
        PhaseSpec(PRO_MONTHLY, date(2025, 2, 1), date(2025, 5, 1), "new", False, "paused"),
        PhaseSpec(PRO_MONTHLY, date(2025, 9, 1), None, "reactivation", False, None),
    ]

    # 9: annual plan spanning a renewal — two invoices expected a year apart.
    scenarios[9] = [
        PhaseSpec(BASIC_ANNUAL, date(2024, 6, 1), None, "new", False, None),
    ]

    # 10: still active, used purely as the "clean" multi-line-invoice and
    # payment-outcome scenario (see PAYMENT_OUTCOMES below).
    scenarios[10] = [
        PhaseSpec(PRO_MONTHLY, date(2025, 4, 1), None, "new", False, None),
    ]

    return scenarios


# Scripted payment behavior for specific (customer_id, invoice_sequence)
# pairs, where invoice_sequence is the 0-indexed invoice number within that
# customer's billing history. Anything not listed here gets the default
# "paid in full, on time" behavior.
NAMED_PAYMENT_OUTCOMES: dict[tuple[int, int], PaymentOutcome] = {
    (6, 2): PaymentOutcome("failed_then_retry"),  # last invoice before cancelling
    (7, 0): PaymentOutcome(
        "full", refund="full", refund_delay_days=50
    ),  # fully refunded after cancellation, late enough to land after period close
    (8, 0): PaymentOutcome("full", refund="partial"),  # partially refunded
    (9, 0): PaymentOutcome("partial"),  # first annual invoice only partly paid
    (10, 1): PaymentOutcome("unpaid"),  # one invoice never gets paid
    (10, 2): PaymentOutcome("late"),  # payment arrives well after the due date
}


# ---------------------------------------------------------------------------
# Randomized chains for all other customers
# ---------------------------------------------------------------------------

_OUTCOME_WEIGHTS = [
    ("steady", 0.60),
    ("cancelled", 0.15),
    ("upgraded", 0.10),
    ("downgraded", 0.05),
    ("reactivated", 0.05),
    ("trial_then_paid", 0.05),
]


def _weighted_choice(pairs: list[tuple[str, float]], rng: random.Random) -> str:
    labels = [p[0] for p in pairs]
    weights = [p[1] for p in pairs]
    return rng.choices(labels, weights=weights, k=1)[0]


def _random_chain(customer_id: int, signup_date: date, rng: random.Random) -> list[PhaseSpec]:
    earliest_start = max(signup_date, date(2024, 6, 1))
    latest_start = TODAY - timedelta(days=90)
    if earliest_start >= latest_start:
        earliest_start = latest_start - timedelta(days=1)
    span_days = (latest_start - earliest_start).days
    start = earliest_start + timedelta(days=rng.randint(0, max(span_days, 0)))

    plan_id = rng.choice([BASIC_MONTHLY, BASIC_ANNUAL, PRO_MONTHLY, PRO_ANNUAL])
    outcome = _weighted_choice(_OUTCOME_WEIGHTS, rng)

    phases: list[PhaseSpec] = []

    if outcome == "trial_then_paid":
        trial_end = start + timedelta(days=14)
        phases.append(PhaseSpec(plan_id, start, trial_end, "trial", True, "upgraded"))
        phases.append(PhaseSpec(plan_id, trial_end, None, "new", False, None))
        return phases

    if outcome == "steady":
        phases.append(PhaseSpec(plan_id, start, None, "new", False, None))
        return phases

    if outcome == "cancelled":
        end = start + timedelta(days=rng.randint(30, 240))
        if end >= TODAY:
            end = TODAY - timedelta(days=1)
        phases.append(PhaseSpec(plan_id, start, end, "new", False, "cancelled"))
        return phases

    if outcome == "upgraded":
        change = start + timedelta(days=rng.randint(60, 200))
        if change >= TODAY:
            phases.append(PhaseSpec(plan_id, start, None, "new", False, None))
            return phases
        new_plan = PRO_MONTHLY if plan_id in (BASIC_MONTHLY, BASIC_ANNUAL) else plan_id
        phases.append(PhaseSpec(plan_id, start, change, "new", False, "upgraded"))
        phases.append(PhaseSpec(new_plan, change, None, "upgrade", False, None))
        return phases

    if outcome == "downgraded":
        change = start + timedelta(days=rng.randint(60, 200))
        if change >= TODAY:
            phases.append(PhaseSpec(plan_id, start, None, "new", False, None))
            return phases
        new_plan = BASIC_MONTHLY if plan_id in (PRO_MONTHLY, PRO_ANNUAL) else plan_id
        phases.append(PhaseSpec(plan_id, start, change, "new", False, "downgraded"))
        phases.append(PhaseSpec(new_plan, change, None, "downgrade", False, None))
        return phases

    if outcome == "reactivated":
        end = start + timedelta(days=rng.randint(30, 120))
        reactivate = end + timedelta(days=rng.randint(60, 150))
        if reactivate >= TODAY:
            phases.append(PhaseSpec(plan_id, start, end, "new", False, "cancelled"))
            return phases
        phases.append(PhaseSpec(plan_id, start, end, "new", False, "cancelled"))
        phases.append(PhaseSpec(plan_id, reactivate, None, "reactivation", False, None))
        return phases

    raise AssertionError(f"unhandled outcome: {outcome}")


# ---------------------------------------------------------------------------
# Flatten phases into subscriptions / invoices / invoice_lines / payments /
# refunds
# ---------------------------------------------------------------------------


def _line_amount(quantity: int, unit_amount: float) -> Decimal:
    return (Decimal(quantity) * Decimal(str(unit_amount))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _billing_periods(phase: PhaseSpec) -> list[tuple[date, date]]:
    """One (period_start, period_end) per invoice this phase generates."""
    if phase.is_trial:
        return []

    plan = PLANS_BY_ID[phase.plan_id]
    step_months = 1 if plan["billing_interval"] == "monthly" else 12

    end = phase.end_date or TODAY
    periods = []
    period_start = phase.start_date
    while period_start < end:
        period_end = _months_later(period_start, step_months)
        if period_end > end:
            break  # don't invoice a partial period that was never actually billed
        periods.append((period_start, period_end))
        period_start = period_end
    return periods


def build_dataset(customers: pd.DataFrame, seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = random.Random(seed)

    signup_by_customer = dict(zip(customers["customer_id"], customers["signup_date"], strict=True))

    chains: dict[int, list[PhaseSpec]] = dict(_named_scenarios())
    other_customer_ids = [
        cid for cid in customers["customer_id"] if cid not in NAMED_SCENARIO_CUSTOMER_IDS
    ]
    sampled_ids = rng.sample(other_customer_ids, k=min(240, len(other_customer_ids)))
    for customer_id in sampled_ids:
        signup = signup_by_customer[customer_id]
        if isinstance(signup, str):
            signup = date.fromisoformat(signup)
        chains[customer_id] = _random_chain(customer_id, signup, rng)

    subscription_rows = []
    invoice_rows = []
    invoice_line_rows = []
    payment_rows = []
    refund_rows = []

    subscription_id = 1
    invoice_id = 1
    invoice_line_id = 1
    payment_id = 1
    refund_id = 1

    for customer_id, phases in chains.items():
        chain_id = customer_id  # one chain per customer in this synthetic dataset
        invoice_sequence = 0
        for phase in phases:
            plan = PLANS_BY_ID[phase.plan_id]
            subscription_rows.append(
                {
                    "subscription_id": subscription_id,
                    "subscription_chain_id": chain_id,
                    "customer_id": customer_id,
                    "plan_id": phase.plan_id,
                    "phase_start_date": phase.start_date,
                    "phase_end_date": phase.end_date,
                    "phase_type": phase.phase_type,
                    "is_trial": phase.is_trial,
                    "ended_reason": phase.ended_reason,
                }
            )

            for period_start, period_end in _billing_periods(phase):
                outcome = NAMED_PAYMENT_OUTCOMES.get(
                    (customer_id, invoice_sequence),
                    PaymentOutcome("full"),
                )
                invoice_date = period_start
                lines = [("Membership - " + plan["plan_name"], 1, plan["price"])]
                if customer_id == 10 and invoice_sequence == 0:
                    lines.append(("One-time setup fee", 1, 5.00))

                line_total = sum(
                    (_line_amount(qty, amt) for _, qty, amt in lines), start=Decimal("0.00")
                )
                for description, qty, unit_amount in lines:
                    invoice_line_rows.append(
                        {
                            "invoice_line_id": invoice_line_id,
                            "invoice_id": invoice_id,
                            "subscription_id": subscription_id,
                            "description": description,
                            "quantity": qty,
                            "unit_amount": unit_amount,
                            "amount": float(_line_amount(qty, unit_amount)),
                        }
                    )
                    invoice_line_id += 1

                invoice_rows.append(
                    {
                        "invoice_id": invoice_id,
                        "subscription_id": subscription_id,
                        "customer_id": customer_id,
                        "invoice_date": invoice_date,
                        "period_start": period_start,
                        "period_end": period_end,
                        "amount": float(line_total),
                    }
                )

                payment_id, refund_id = _generate_payments_for_invoice(
                    invoice_id=invoice_id,
                    invoice_date=invoice_date,
                    amount=line_total,
                    outcome=outcome,
                    payment_id=payment_id,
                    refund_id=refund_id,
                    rng=rng,
                    payment_rows=payment_rows,
                    refund_rows=refund_rows,
                )

                invoice_id += 1
                invoice_sequence += 1

            subscription_id += 1

    return {
        "plans": pd.DataFrame(PLANS),
        "subscriptions": pd.DataFrame(subscription_rows),
        "invoices": pd.DataFrame(invoice_rows),
        "invoice_lines": pd.DataFrame(invoice_line_rows),
        "payments": pd.DataFrame(payment_rows),
        "refunds": pd.DataFrame(refund_rows),
    }


def _generate_payments_for_invoice(
    *,
    invoice_id: int,
    invoice_date: date,
    amount: Decimal,
    outcome: PaymentOutcome,
    payment_id: int,
    refund_id: int,
    rng: random.Random,
    payment_rows: list[dict],
    refund_rows: list[dict],
) -> tuple[int, int]:
    method = rng.choice(PAYMENT_METHODS)
    succeeded_payment_id: int | None = None
    succeeded_amount = Decimal("0.00")

    if outcome.kind == "unpaid":
        payment_rows.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "payment_date": invoice_date + timedelta(days=3),
                "amount": float(amount),
                "payment_method": method,
                "status": "failed",
                "is_retry": False,
            }
        )
        payment_id += 1

    elif outcome.kind == "failed_then_retry":
        payment_rows.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "payment_date": invoice_date + timedelta(days=1),
                "amount": float(amount),
                "payment_method": method,
                "status": "failed",
                "is_retry": False,
            }
        )
        payment_id += 1
        succeeded_payment_id = payment_id
        succeeded_amount = amount
        payment_rows.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "payment_date": invoice_date + timedelta(days=4),
                "amount": float(amount),
                "payment_method": method,
                "status": "succeeded",
                "is_retry": True,
            }
        )
        payment_id += 1

    elif outcome.kind == "partial":
        partial_amount = (amount / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        succeeded_payment_id = payment_id
        succeeded_amount = partial_amount
        payment_rows.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "payment_date": invoice_date + timedelta(days=2),
                "amount": float(partial_amount),
                "payment_method": method,
                "status": "succeeded",
                "is_retry": False,
            }
        )
        payment_id += 1

    elif outcome.kind == "late":
        succeeded_payment_id = payment_id
        succeeded_amount = amount
        payment_rows.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "payment_date": invoice_date + timedelta(days=45),
                "amount": float(amount),
                "payment_method": method,
                "status": "succeeded",
                "is_retry": False,
            }
        )
        payment_id += 1

    else:  # "full"
        succeeded_payment_id = payment_id
        succeeded_amount = amount
        payment_rows.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "payment_date": invoice_date + timedelta(days=rng.randint(0, 3)),
                "amount": float(amount),
                "payment_method": method,
                "status": "succeeded",
                "is_retry": False,
            }
        )
        payment_id += 1

    if outcome.refund and succeeded_payment_id is not None:
        refund_amount = (
            succeeded_amount
            if outcome.refund == "full"
            else (succeeded_amount / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        refund_rows.append(
            {
                "refund_id": refund_id,
                "payment_id": succeeded_payment_id,
                "refund_date": invoice_date + timedelta(days=outcome.refund_delay_days),
                "amount": float(refund_amount),
                "reason": "customer_request",
            }
        )
        refund_id += 1

    return payment_id, refund_id


def main() -> None:
    if not CUSTOMERS_CSV.exists():
        raise FileNotFoundError(
            f"{CUSTOMERS_CSV} not found — run scripts/generate_synthetic_data.py first"
        )
    customers = pd.read_csv(CUSTOMERS_CSV)

    tables = build_dataset(customers)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(OUTPUT_DIR / f"{name}.csv", index=False)

    counts = ", ".join(f"{len(df)} {name}" for name, df in tables.items())
    print(f"Wrote {counts} to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
