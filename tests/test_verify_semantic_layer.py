"""Tests for scripts/verify_semantic_layer.py's comparison and schema-resolution logic.

compare() is pure (no database) and tested directly against constructed
DataFrames. resolved_sql() needs a reachable Postgres, but deliberately
*not* a dbt-built warehouse: CI runs `pytest` before `dbt build` (see
.github/workflows/ci.yml), so a resolved_sql() test depending on the real
mart_revenue_reconciliation_by_period/int_active_customers_by_period
tables existing would fail there every time, the same way
tests/test_resolve_marts_schema.py's own tests would have. These use the
identical throwaway-schema pattern for the identical reason.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts import verify_semantic_layer
from scripts.ingest import get_engine
from scripts.verify_semantic_layer import compare, resolved_sql

MARTS_SCHEMA = "verify_semantic_layer_test_marts"
INTERMEDIATE_SCHEMA = "verify_semantic_layer_test_intermediate"


def _postgres_reachable() -> bool:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False


pg_only = pytest.mark.skipif(
    not _postgres_reachable(), reason="Postgres not reachable — run `docker compose up -d` first"
)


def test_identical_frames_produce_no_mismatches() -> None:
    mf_df = pd.DataFrame({"metric_time__month": ["2025-01", "2025-02"], "revenue": [100, 200]})
    direct_df = pd.DataFrame({"metric_time__month": ["2025-01", "2025-02"], "revenue": [100, 200]})
    assert compare("revenue", "metric_time__month", mf_df, direct_df) == []


def test_a_real_divergence_is_reported() -> None:
    mf_df = pd.DataFrame({"metric_time__month": ["2025-01"], "revenue": [100]})
    direct_df = pd.DataFrame({"metric_time__month": ["2025-01"], "revenue": [999]})
    mismatches = compare("revenue", "metric_time__month", mf_df, direct_df)
    assert len(mismatches) == 1
    assert "mf=100" in mismatches[0]
    assert "direct=999" in mismatches[0]


def test_rounding_within_a_cent_is_not_a_mismatch() -> None:
    mf_df = pd.DataFrame({"metric_time__month": ["2025-01"], "revenue": [100.001]})
    direct_df = pd.DataFrame({"metric_time__month": ["2025-01"], "revenue": [100.004]})
    assert compare("revenue", "metric_time__month", mf_df, direct_df) == []


def test_null_on_either_side_is_treated_as_zero_not_a_crash() -> None:
    mf_df = pd.DataFrame({"metric_time__month": ["2025-01"], "revenue": [None]})
    direct_df = pd.DataFrame({"metric_time__month": ["2025-01"], "revenue": [0]})
    assert compare("revenue", "metric_time__month", mf_df, direct_df) == []


def test_a_row_present_on_only_one_side_is_a_mismatch() -> None:
    mf_df = pd.DataFrame({"metric_time__month": ["2025-01", "2025-02"], "revenue": [100, 200]})
    direct_df = pd.DataFrame({"metric_time__month": ["2025-01"], "revenue": [100]})
    mismatches = compare("revenue", "metric_time__month", mf_df, direct_df)
    assert len(mismatches) == 1
    assert "2025-02" in mismatches[0]


@pytest.fixture
def engine() -> Engine:
    return get_engine()


# Deliberately NOT autouse, and not marked itself (pytest doesn't allow
# marks on fixtures) -- only the tests that actually need real schemas/
# tables request it by name, so the pure compare() tests above never
# touch Postgres at all, and a skipped @pg_only test never triggers this
# fixture's setup either (pytest skips before fixture setup runs).
@pytest.fixture
def isolated_schemas(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(verify_semantic_layer, "MARTS_SCHEMAS", (MARTS_SCHEMA,))
    monkeypatch.setattr(verify_semantic_layer, "INTERMEDIATE_SCHEMAS", (INTERMEDIATE_SCHEMA,))
    with engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {MARTS_SCHEMA} cascade"))
        conn.execute(text(f"drop schema if exists {INTERMEDIATE_SCHEMA} cascade"))
        conn.execute(text(f"create schema {MARTS_SCHEMA}"))
        conn.execute(text(f"create schema {INTERMEDIATE_SCHEMA}"))
        conn.execute(
            text(f"create table {MARTS_SCHEMA}.mart_revenue_reconciliation_by_period (id int)")
        )
        conn.execute(
            text(f"create table {INTERMEDIATE_SCHEMA}.int_active_customers_by_period (id int)")
        )
    yield
    with engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {MARTS_SCHEMA} cascade"))
        conn.execute(text(f"drop schema if exists {INTERMEDIATE_SCHEMA} cascade"))


@pg_only
def test_resolved_sql_substitutes_the_marts_schema_placeholder(
    engine: Engine, isolated_schemas: None
) -> None:
    sql = resolved_sql(
        engine, "select 1 from {marts_schema}.mart_revenue_reconciliation_by_period"
    )
    assert sql == f"select 1 from {MARTS_SCHEMA}.mart_revenue_reconciliation_by_period"


@pg_only
def test_resolved_sql_substitutes_the_intermediate_schema_placeholder(
    engine: Engine, isolated_schemas: None
) -> None:
    sql = resolved_sql(
        engine, "select 1 from {intermediate_schema}.int_active_customers_by_period"
    )
    assert sql == f"select 1 from {INTERMEDIATE_SCHEMA}.int_active_customers_by_period"


@pg_only
def test_resolved_sql_leaves_a_template_with_no_placeholders_unchanged(engine: Engine) -> None:
    # No {marts_schema}/{intermediate_schema} placeholder in this template
    # -- resolved_sql() never touches the database for it, so this test
    # deliberately doesn't request isolated_schemas.
    assert resolved_sql(engine, "select 1") == "select 1"


@pg_only
def test_resolved_sql_raises_a_clear_error_when_the_proxy_table_is_missing_everywhere(
    engine: Engine, isolated_schemas: None
) -> None:
    # resolved_sql() resolves {marts_schema} via a fixed proxy table
    # (mart_revenue_reconciliation_by_period), not whatever table the
    # caller's own template happens to reference -- dropping the proxy
    # from the isolated schema (leaving it genuinely nowhere) is what
    # actually exercises the "neither schema has it" branch.
    with engine.begin() as conn:
        conn.execute(text(f"drop table {MARTS_SCHEMA}.mart_revenue_reconciliation_by_period"))
    with pytest.raises(RuntimeError, match=MARTS_SCHEMA):
        resolved_sql(engine, "select 1 from {marts_schema}.mart_revenue_reconciliation_by_period")
