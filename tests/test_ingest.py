"""Tests for the raw-schema ingestion step.

These need a reachable Postgres (the same one docker-compose / CI provides)
and are skipped automatically if one isn't available, so `pytest` still
works for someone who hasn't run `docker compose up` yet.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from scripts import generate_synthetic_data, ingest


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


def test_ingest_loads_expected_row_counts():
    ingest.main()
    engine = ingest.get_engine()
    for table in ingest.TABLES:
        csv_path = generate_synthetic_data.OUTPUT_DIR / f"{table}.csv"
        expected_rows = len(pd.read_csv(csv_path))
        with engine.connect() as conn:
            actual_rows = conn.execute(text(f"select count(*) from raw.{table}")).scalar()
        assert actual_rows == expected_rows, f"raw.{table} row count mismatch"


def test_ingest_is_idempotent_across_repeated_runs():
    ingest.main()
    ingest.main()
    engine = ingest.get_engine()
    for table in ingest.TABLES:
        csv_path = generate_synthetic_data.OUTPUT_DIR / f"{table}.csv"
        expected_rows = len(pd.read_csv(csv_path))
        with engine.connect() as conn:
            actual_rows = conn.execute(text(f"select count(*) from raw.{table}")).scalar()
        assert actual_rows == expected_rows, f"raw.{table} row count changed after a second run"


def test_ingest_adds_loaded_at_to_legacy_table():
    # Regression test for a real bug: a table created before _loaded_at
    # existed (e.g. a persistent local volume from an earlier version of
    # this script) doesn't have that column. Truncating it and then
    # appending a DataFrame that includes _loaded_at fails, because by
    # then the table is already empty. Ingestion must add the missing
    # column rather than fail partway through.
    #
    # Rebuilt from scratch as a bare table (not via ALTER ... DROP COLUMN
    # on the real table) so this doesn't collide with dbt staging views,
    # which reference _loaded_at transitively through `select *` and would
    # block dropping it — a separate concern from what this test checks.
    ingest.main()
    engine = ingest.get_engine()

    with engine.begin() as conn:
        conn.execute(text("drop table if exists raw.customers cascade"))
        conn.execute(
            text(
                "create table raw.customers ("
                "customer_id integer, first_name text, last_name text, "
                "email text, signup_date date, region text, country text)"
            )
        )

    ingest.main()  # must add _loaded_at rather than fail

    with engine.connect() as conn:
        row_count = conn.execute(text("select count(*) from raw.customers")).scalar()
        loaded_at_is_set = conn.execute(
            text("select count(*) from raw.customers where _loaded_at is null")
        ).scalar()

    csv_path = generate_synthetic_data.OUTPUT_DIR / "customers.csv"
    assert row_count == len(pd.read_csv(csv_path))
    assert loaded_at_is_set == 0


def test_ingest_tolerates_dependent_views():
    # Regression test for a real bug: re-ingesting via if_exists="replace"
    # used to DROP TABLE, which Postgres refuses once a view depends on it
    # (dbt's staging models are views over these exact tables). Ingestion
    # must keep working once downstream views exist.
    ingest.main()
    engine = ingest.get_engine()

    with engine.begin() as conn:
        conn.execute(
            text(
                "create or replace view raw.test_dependent_view as "
                "select customer_id from raw.customers"
            )
        )

    try:
        ingest.main()  # must not raise DependentObjectsStillExist
        with engine.connect() as conn:
            row_count = conn.execute(text("select count(*) from raw.customers")).scalar()
        csv_path = generate_synthetic_data.OUTPUT_DIR / "customers.csv"
        assert row_count == len(pd.read_csv(csv_path))
    finally:
        with engine.begin() as conn:
            conn.execute(text("drop view if exists raw.test_dependent_view"))
