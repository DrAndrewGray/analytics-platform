"""Tests for the events-schema ingestion step.

Mirrors tests/test_ingest_billing.py: needs a reachable Postgres and
skips otherwise, and runs against an isolated TEST_SCHEMA rather than
the real `raw_events` schema dbt builds its staging views from.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from scripts import generate_event_data, generate_synthetic_data, ingest, ingest_events

TEST_SCHEMA = "raw_events_test"


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
    if not (Path(generate_event_data.OUTPUT_DIR) / "events.csv").exists():
        generate_event_data.main()


@pytest.fixture(scope="module", autouse=True)
def _reset_test_schema():
    engine = ingest.get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {TEST_SCHEMA} cascade"))
    yield
    with engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {TEST_SCHEMA} cascade"))


def test_ingest_events_loads_expected_row_count():
    ingest_events.main(schema=TEST_SCHEMA)
    engine = ingest.get_engine()
    expected_rows = len(pd.read_csv(generate_event_data.OUTPUT_DIR / "events.csv"))
    with engine.connect() as conn:
        actual_rows = conn.execute(text(f"select count(*) from {TEST_SCHEMA}.events")).scalar()
    assert actual_rows == expected_rows


def test_ingest_events_preserves_timestamp_precision():
    # Regression test for a real bug: the shared date-coercion helper only
    # handled plain dates (%Y-%m-%d), so a column with a time component
    # (event_timestamp) would either stay TEXT or get silently truncated
    # to a date, losing the time-of-day information session-gap analysis
    # depends on entirely.
    ingest_events.main(schema=TEST_SCHEMA)
    engine = ingest.get_engine()
    with engine.connect() as conn:
        data_type = conn.execute(
            text(
                "select data_type from information_schema.columns "
                "where table_schema = :schema and table_name = 'events' "
                "and column_name = 'event_timestamp'"
            ),
            {"schema": TEST_SCHEMA},
        ).scalar()
    assert data_type in ("timestamp without time zone", "timestamp with time zone")
