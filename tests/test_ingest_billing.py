"""Tests for the billing-schema ingestion step.

Mirrors tests/test_ingest.py: needs a reachable Postgres and skips
otherwise, and runs entirely against an isolated TEST_SCHEMA rather than
the real `raw_billing` schema dbt builds its staging views from.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from scripts import generate_billing_data, generate_synthetic_data, ingest, ingest_billing

TEST_SCHEMA = "raw_billing_test"


def _postgres_reachable() -> bool:
    try:
        engine = ingest.get_engine()
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — run `docker compose up -d` first",
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_csvs_exist():
    if not (Path(generate_synthetic_data.OUTPUT_DIR) / "customers.csv").exists():
        generate_synthetic_data.main()
    if not (Path(generate_billing_data.OUTPUT_DIR) / "plans.csv").exists():
        generate_billing_data.main()


@pytest.fixture(scope="module", autouse=True)
def _reset_test_schema():
    engine = ingest.get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {TEST_SCHEMA} cascade"))
    yield
    with engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {TEST_SCHEMA} cascade"))


def test_ingest_billing_loads_expected_row_counts():
    ingest_billing.main(schema=TEST_SCHEMA)
    engine = ingest.get_engine()
    for table in ingest_billing.TABLES:
        csv_path = generate_billing_data.OUTPUT_DIR / f"{table}.csv"
        expected_rows = len(pd.read_csv(csv_path))
        with engine.connect() as conn:
            actual_rows = conn.execute(
                text(f"select count(*) from {TEST_SCHEMA}.{table}")
            ).scalar()
        assert actual_rows == expected_rows, f"{TEST_SCHEMA}.{table} row count mismatch"


def test_ingest_billing_is_idempotent_across_repeated_runs():
    ingest_billing.main(schema=TEST_SCHEMA)
    ingest_billing.main(schema=TEST_SCHEMA)
    engine = ingest.get_engine()
    for table in ingest_billing.TABLES:
        csv_path = generate_billing_data.OUTPUT_DIR / f"{table}.csv"
        expected_rows = len(pd.read_csv(csv_path))
        with engine.connect() as conn:
            actual_rows = conn.execute(
                text(f"select count(*) from {TEST_SCHEMA}.{table}")
            ).scalar()
        assert actual_rows == expected_rows, (
            f"{TEST_SCHEMA}.{table} row count changed after a second run"
        )


def test_ingest_billing_does_not_collide_with_retail_payments():
    # Regression test for a real bug: the billing generator originally
    # wrote payments.csv into the same data/raw/ directory as the retail
    # generator, silently overwriting it (same filename, different
    # schema). Billing payments and retail payments must stay distinct
    # both on disk and in the warehouse.
    ingest_billing.main(schema=TEST_SCHEMA)
    engine = ingest.get_engine()
    with engine.connect() as conn:
        columns = conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema = :schema and table_name = 'payments'"
            ),
            {"schema": TEST_SCHEMA},
        ).scalars().all()
    assert "invoice_id" in columns
    assert "order_id" not in columns
