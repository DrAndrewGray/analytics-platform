"""Verify governed metrics reconcile with their source marts.

For each metric below, queries it via `mf query` — the only way anything
in this repo is allowed to compute a governed number — and compares the
result against a direct SQL query of the metric's own source mart. Same
independent-recomputation discipline as Phase 4/5's own
assert_*_matches_source_facts.sql tests: a mismatch here would mean
MetricFlow's generated SQL diverged from the mart's own straightforward
aggregate, which should be structurally impossible given every semantic
model here is `sum`/`count_distinct` directly on an already-tested mart
column (see docs/semantic_layer_strategy.md for why that's true by
construction, not by luck).

Only covers `simple` metrics with a 1:1 mart mapping — the `derived`
ratio metrics (churn_rate, retention_rate, etc.) are formulas over these
same simple metrics, verified by hand against the mart during
development (see docs/metric_definitions_semantic.md) rather than
re-verified here, since a passing check on their own inputs already
implies their arithmetic is exercised.

Usage:
    uv run python scripts/verify_semantic_layer.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.generate_alert_report import resolve_schema
from scripts.ingest import get_engine

DBT_DIR = Path(__file__).resolve().parent.parent / "dbt"

# dbt builds marts/intermediate models under a schema name that depends on
# which target built them (analytics_marts vs. analytics_ci_marts,
# analytics_intermediate vs. analytics_ci_intermediate — see
# dbt/profiles.yml). The `sql` templates below use {marts_schema}/
# {intermediate_schema} placeholders, resolved at runtime via
# resolve_schema() (reused from scripts/generate_alert_report.py, not
# duplicated) rather than hardcoded — hardcoding analytics_marts directly
# is exactly the bug that broke scripts/inject_failure.py's
# late-arriving-refund scenario the first time it ran in a ci-only
# environment (see the README's "Bugs this caught"); this script would
# have hit the identical failure the first time it ran in CI if the
# schema names here weren't resolved the same way.
MARTS_SCHEMAS = ("analytics_marts", "analytics_ci_marts")
INTERMEDIATE_SCHEMAS = ("analytics_intermediate", "analytics_ci_intermediate")

RECONCILIATIONS: list[dict[str, Any]] = [
    {
        "metric": "net_booked_revenue",
        "group_by": "metric_time__month",
        "key_column": "metric_time__month",
        "sql": """
            select period_start_date::date as metric_time__month,
                total_net_booked_revenue as net_booked_revenue
            from {marts_schema}.mart_revenue_reconciliation_by_period
            order by period_start_date
        """,
    },
    {
        "metric": "cash_collected_against_bookings",
        "group_by": "metric_time__month",
        "key_column": "metric_time__month",
        "sql": """
            select period_start_date::date as metric_time__month,
                total_collected_against_bookings as cash_collected_against_bookings
            from {marts_schema}.mart_revenue_reconciliation_by_period
            order by period_start_date
        """,
    },
    {
        "metric": "cash_in",
        "group_by": "metric_time__month",
        "key_column": "metric_time__month",
        "sql": """
            select period_start_date::date as metric_time__month,
                total_cash_in as cash_in
            from {marts_schema}.mart_cash_movements_by_period
            order by period_start_date
        """,
    },
    {
        "metric": "cash_out",
        "group_by": "metric_time__month",
        "key_column": "metric_time__month",
        "sql": """
            select period_start_date::date as metric_time__month,
                total_cash_out as cash_out
            from {marts_schema}.mart_cash_movements_by_period
            order by period_start_date
        """,
    },
    {
        "metric": "mrr",
        "group_by": "metric_time__month",
        "key_column": "metric_time__month",
        "sql": """
            select activity_month::date as metric_time__month, closing_mrr as mrr
            from {marts_schema}.mart_mrr_movements
            order by activity_month
        """,
    },
    {
        "metric": "active_customers",
        "group_by": "metric_time__month",
        "key_column": "metric_time__month",
        "sql": """
            select period_start_date::date as metric_time__month,
                count(distinct customer_id) as active_customers
            from {intermediate_schema}.int_active_customers_by_period
            group by period_start_date
            order by period_start_date
        """,
    },
    {
        "metric": "viewers,purchasers",
        "group_by": "metric_time__day",
        "key_column": "metric_time__day",
        "sql": """
            select activity_date::date as metric_time__day, viewers, purchasers
            from {marts_schema}.mart_funnel_conversion
            order by activity_date
        """,
    },
]


def resolved_sql(engine: Engine, sql_template: str) -> str:
    kwargs = {}
    if "{marts_schema}" in sql_template:
        schema = resolve_schema(engine, "mart_revenue_reconciliation_by_period", MARTS_SCHEMAS)
        if schema is None:
            raise RuntimeError(f"Neither of {MARTS_SCHEMAS} exists in this database.")
        kwargs["marts_schema"] = schema
    if "{intermediate_schema}" in sql_template:
        schema = resolve_schema(
            engine, "int_active_customers_by_period", INTERMEDIATE_SCHEMAS
        )
        if schema is None:
            raise RuntimeError(f"Neither of {INTERMEDIATE_SCHEMAS} exists in this database.")
        kwargs["intermediate_schema"] = schema
    return sql_template.format(**kwargs)


def run_mf_query(metrics: str, group_by: str) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        csv_path = Path(f.name)
    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "mf",
                "query",
                "--metrics",
                metrics,
                "--group-by",
                group_by,
                "--csv",
                str(csv_path),
                "--quiet",
            ],
            cwd=DBT_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"mf query failed for '{metrics}':\n{result.stderr}")
        return pd.read_csv(csv_path)
    finally:
        csv_path.unlink(missing_ok=True)


def _as_rounded_float(value: object) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    return round(float(value), 2)  # type: ignore[arg-type]


def compare(
    metric_label: str, key_column: str, mf_df: pd.DataFrame, direct_df: pd.DataFrame
) -> list[str]:
    # A plain row-by-row comparison, not a vectorized pandas chain: this
    # project's own convention (see generate_synthetic_data.py's comment
    # on why it avoids groupby(...)[col].sum()) is to skip pandas method
    # chains pyright can't resolve to a concrete type, in favor of
    # something a type checker — and a human — can follow directly.
    mismatches = []
    merged = mf_df.merge(direct_df, on=key_column, how="outer", suffixes=("_mf", "_direct"))
    value_columns = [c for c in direct_df.columns if c != key_column]

    for column in value_columns:
        mf_col, direct_col = f"{column}_mf", f"{column}_direct"
        if mf_col not in merged.columns or direct_col not in merged.columns:
            mismatches.append(f"{metric_label}: column '{column}' missing from one side entirely")
            continue
        for _, row in merged.iterrows():
            mf_value = _as_rounded_float(row[mf_col])
            direct_value = _as_rounded_float(row[direct_col])
            if mf_value != direct_value:
                mismatches.append(
                    f"{metric_label}.{column} at {key_column}={row[key_column]}: "
                    f"mf={mf_value!r} direct={direct_value!r}"
                )
    return mismatches


def main() -> None:
    engine = get_engine()
    all_mismatches: list[str] = []

    for recon in RECONCILIATIONS:
        mf_df = run_mf_query(recon["metric"], recon["group_by"])
        sql = resolved_sql(engine, recon["sql"])
        with engine.connect() as conn:
            direct_df = pd.read_sql(text(sql), conn)
        mf_df[recon["key_column"]] = pd.to_datetime(mf_df[recon["key_column"]]).dt.date
        direct_df[recon["key_column"]] = pd.to_datetime(direct_df[recon["key_column"]]).dt.date

        mismatches = compare(recon["metric"], recon["key_column"], mf_df, direct_df)
        if mismatches:
            all_mismatches.extend(mismatches)
            print(f"MISMATCH: {recon['metric']} ({len(mismatches)} row(s) diverge)")
        else:
            print(
                f"OK: {recon['metric']} matches its source mart "
                f"({len(direct_df)} periods checked)"
            )

    if all_mismatches:
        print(f"\n{len(all_mismatches)} mismatch(es) found:")
        for m in all_mismatches:
            print(f"  - {m}")
        sys.exit(1)

    print(f"\nAll {len(RECONCILIATIONS)} governed metrics reconcile with their source marts.")


if __name__ == "__main__":
    main()
