"""Deliberately break the real Postgres data behind Meridian, one named scenario at a time.

No separate "fake broken" environment: every scenario runs real DDL/DML
against the actual raw schemas dbt builds from, because the point is
demonstrating what the actual pipeline does when its actual inputs break,
not a simulation of that. Recovery, for every scenario, is the same path
already used throughout the project whenever data needs to be reset:
regenerate the synthetic data and re-run ingestion, then `dbt build` again
(see docs/reliability_strategy.md).

Some scenarios (drop-column, change-column-type) mutate the shared `raw`
schema directly, which both the dev and ci dbt targets build from — so
those two scenarios affect both targets at once. That's a real property of
this project's architecture (see docs/reliability_strategy.md), not a bug
in this script; recovery already rebuilds both targets anyway.

Usage:
    uv run python scripts/inject_failure.py list
    uv run python scripts/inject_failure.py <scenario>
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.ingest import get_engine

load_dotenv()


def scenario_drop_column(engine: Engine) -> str:
    """A required source column disappears (raw.orders.channel)."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE raw.orders DROP COLUMN channel CASCADE"))
    return (
        "Dropped raw.orders.channel (CASCADE). stg_orders and everything "
        "downstream of it, in both the dev and ci schemas, no longer exist "
        "as views — the next `dbt build` will fail trying to recreate "
        "stg_orders, which still selects `channel as order_channel`."
    )


def scenario_change_column_type(engine: Engine) -> str:
    """An upstream column changes type (raw.orders.customer_id: bigint -> text)."""
    with engine.begin() as conn:
        conn.execute(text("DROP VIEW IF EXISTS analytics_staging.stg_orders CASCADE"))
        conn.execute(text("DROP VIEW IF EXISTS analytics_ci_staging.stg_orders CASCADE"))
        conn.execute(text("ALTER TABLE raw.orders ALTER COLUMN customer_id TYPE text"))
    return (
        "Changed raw.orders.customer_id from bigint to text (after dropping "
        "the dependent stg_orders views in both schemas, since Postgres "
        "won't ALTER COLUMN TYPE with a view attached). stg_orders will "
        "recreate fine on the next `dbt build` — it doesn't cast "
        "customer_id — but fct_orders is contracted with "
        "customer_id: bigint (see docs/data_contracts.md), so the build "
        "will fail there with a contract violation, not a generic "
        "compilation error."
    )


def scenario_bad_status(engine: Engine) -> str:
    """An unexpected status value arrives (raw.orders.status = 'disputed')."""
    with engine.begin() as conn:
        next_id = conn.execute(text("SELECT max(order_id) + 1 FROM raw.orders")).scalar_one()
        customer_id = conn.execute(
            text("SELECT customer_id FROM raw.customers LIMIT 1")
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO raw.orders (order_id, customer_id, order_date, status, channel)
                VALUES (:order_id, :customer_id, current_date, 'disputed', 'web')
                """
            ),
            {"order_id": next_id, "customer_id": customer_id},
        )
    return (
        f"Inserted raw.orders.order_id={next_id} with status='disputed', "
        "which stg_orders' accepted_values test doesn't allow "
        "(completed/cancelled/refunded only)."
    )


def scenario_duplicate_pk(engine: Engine) -> str:
    """Duplicate primary keys appear (a second row with an existing order_id)."""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT order_id, customer_id FROM raw.orders ORDER BY order_id LIMIT 1")
        ).one()
        conn.execute(
            text(
                """
                INSERT INTO raw.orders (order_id, customer_id, order_date, status, channel)
                VALUES (:order_id, :customer_id, current_date, 'completed', 'web')
                """
            ),
            {"order_id": row.order_id, "customer_id": row.customer_id},
        )
    return (
        f"Inserted a second raw.orders row with order_id={row.order_id} "
        "(raw.orders has no primary key constraint, so this succeeds). "
        "Caught by unique_stg_orders_order_id at the staging layer, "
        "before fct_orders is even attempted — dbt skips downstream "
        "models when an upstream test fails, so fct_orders' own "
        "primary_key contract constraint never actually gets exercised "
        "by this scenario specifically (verified empirically: the "
        "failure is the staging test, not a contract violation)."
    )


def scenario_broken_fk(engine: Engine) -> str:
    """A foreign key stops resolving (order_items row pointing at a nonexistent order)."""
    with engine.begin() as conn:
        next_id = conn.execute(
            text("SELECT max(order_item_id) + 1 FROM raw.order_items")
        ).scalar_one()
        nonexistent_order_id = conn.execute(
            text("SELECT max(order_id) + 1000 FROM raw.orders")
        ).scalar_one()
        product_id = conn.execute(
            text("SELECT product_id FROM raw.products LIMIT 1")
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO raw.order_items
                    (order_item_id, order_id, product_id, quantity, unit_price, discount)
                VALUES (:item_id, :order_id, :product_id, 1, 9.99, 0)
                """
            ),
            {"item_id": next_id, "order_id": nonexistent_order_id, "product_id": product_id},
        )
    return (
        f"Inserted raw.order_items.order_item_id={next_id} referencing "
        f"order_id={nonexistent_order_id}, which doesn't exist in "
        "raw.orders. Caught by the relationships test on "
        "stg_order_items.order_id, not a database FK (none exists on "
        "these raw tables)."
    )


def scenario_volume_drop(engine: Engine) -> str:
    """Daily event volume suddenly falls (delete most events from a closed month)."""
    with engine.begin() as conn:
        target_month = conn.execute(
            text(
                """
                SELECT date_trunc('month', event_timestamp)::date
                FROM raw_events.events
                GROUP BY 1
                ORDER BY count(*) DESC
                LIMIT 1
                """
            )
        ).scalar_one()
        deleted = conn.execute(
            text(
                """
                DELETE FROM raw_events.events
                WHERE date_trunc('month', event_timestamp) = :target_month
                AND event_id NOT IN (
                    SELECT event_id FROM raw_events.events
                    WHERE date_trunc('month', event_timestamp) = :target_month
                    ORDER BY event_id LIMIT 1
                )
                """
            ),
            {"target_month": target_month},
        ).rowcount
    return (
        f"Deleted {deleted} of raw_events.events' rows from {target_month} "
        "(the busiest month on record), leaving just one row — "
        "mart_volume_anomalies should flag that period as an anomaly on "
        "the next `dbt build`."
    )


def scenario_revenue_spike(engine: Engine) -> str:
    """Revenue jumps beyond a plausible range (one implausibly large order)."""
    with engine.begin() as conn:
        next_order_id = conn.execute(
            text("SELECT max(order_id) + 1 FROM raw.orders")
        ).scalar_one()
        next_item_id = conn.execute(
            text("SELECT max(order_item_id) + 1 FROM raw.order_items")
        ).scalar_one()
        customer_id = conn.execute(
            text("SELECT customer_id FROM raw.customers LIMIT 1")
        ).scalar_one()
        product_id = conn.execute(
            text("SELECT product_id FROM raw.products LIMIT 1")
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO raw.orders (order_id, customer_id, order_date, status, channel)
                VALUES (:order_id, :customer_id, current_date, 'completed', 'web')
                """
            ),
            {"order_id": next_order_id, "customer_id": customer_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO raw.order_items
                    (order_item_id, order_id, product_id, quantity, unit_price, discount)
                VALUES (:item_id, :order_id, :product_id, 1, 5000000, 0)
                """
            ),
            {"item_id": next_item_id, "order_id": next_order_id, "product_id": product_id},
        )
    return (
        f"Inserted order_id={next_order_id} with a single $5,000,000 line "
        "item — the not_implausibly_large test on fct_orders.order_amount "
        "(ceiling: $10,000, see docs/reliability_strategy.md) will catch "
        "it on the next `dbt build`."
    )


def scenario_source_stale(engine: Engine) -> str:
    """A source stops loading (raw.customers backdated past the freshness error threshold)."""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE raw.customers SET _loaded_at = now() - interval '10 days'")
        )
    return (
        "Backdated every raw.customers._loaded_at by 10 days, past the "
        "3-day error_after freshness threshold — `dbt source freshness` "
        "will report raw.customers as ERROR-stale on the next run."
    )


def scenario_late_arriving_refund(engine: Engine) -> str:
    """Late-arriving data changes a closed period (a new refund against a closed invoice)."""
    with engine.begin() as conn:
        invoice = conn.execute(
            text(
                """
                SELECT i.invoice_id, p.payment_id
                FROM raw_billing.invoices AS i
                INNER JOIN raw_billing.payments AS p ON i.invoice_id = p.invoice_id
                INNER JOIN analytics_seeds.accounting_periods AS periods
                    ON i.invoice_date >= periods.period_start_date
                    AND i.invoice_date <= periods.period_end_date
                WHERE periods.closed_at IS NOT NULL
                AND p.status = 'succeeded'
                AND NOT EXISTS (
                    SELECT 1 FROM raw_billing.refunds AS r WHERE r.payment_id = p.payment_id
                )
                ORDER BY i.invoice_date DESC
                LIMIT 1
                """
            )
        ).one()
        next_refund_id = conn.execute(
            text("SELECT max(refund_id) + 1 FROM raw_billing.refunds")
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO raw_billing.refunds (refund_id, payment_id, refund_date, reason, amount)
                SELECT :refund_id, :payment_id, current_date, 'customer_request', amount
                FROM raw_billing.payments WHERE payment_id = :payment_id
                """
            ),
            {"refund_id": next_refund_id, "payment_id": invoice.payment_id},
        )
    return (
        f"Inserted refund_id={next_refund_id} against payment_id="
        f"{invoice.payment_id} (invoice_id={invoice.invoice_id}), dated "
        "today, against an invoice whose accounting period is already "
        "closed. fct_period_close_adjustments will mark it "
        "is_late_adjustment=true on the next `dbt build` — this isn't a "
        "test failure (late adjustments are normal, tracked activity, "
        "not a bug — see docs/metric_definitions_finance.md), it's a "
        "case for scripts/generate_alert_report.py's delta-alert instead."
    )


SCENARIOS: dict[str, Callable[[Engine], str]] = {
    "drop-column": scenario_drop_column,
    "change-column-type": scenario_change_column_type,
    "bad-status": scenario_bad_status,
    "duplicate-pk": scenario_duplicate_pk,
    "broken-fk": scenario_broken_fk,
    "volume-drop": scenario_volume_drop,
    "revenue-spike": scenario_revenue_spike,
    "source-stale": scenario_source_stale,
    "late-arriving-refund": scenario_late_arriving_refund,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=[*SCENARIOS, "list"])
    args = parser.parse_args()

    if args.scenario == "list":
        for name, fn in SCENARIOS.items():
            print(f"{name}: {(fn.__doc__ or '').strip()}")
        return

    engine = get_engine()
    result = SCENARIOS[args.scenario](engine)
    print(f"Injected '{args.scenario}':\n{result}")
    print(
        "\nRecovery: regenerate synthetic data + re-run ingestion + `dbt build` "
        "on both targets (see docs/runbook.md)."
    )


if __name__ == "__main__":
    main()
