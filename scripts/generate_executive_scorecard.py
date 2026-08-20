"""Generate docs/bi/executive_scorecard.html — headline KPIs, one page.

Every number comes from scripts/bi_common.mf_query(), which shells out to
`mf query` — there's no code path here that computes a metric any other
way. This is one of the two "thin BI outputs" the semantic layer phase
demonstrates: same governed definitions as the operational dashboard,
different audience.

Usage:
    uv run python scripts/generate_executive_scorecard.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.bi_common import (
    format_count,
    format_money,
    format_percent,
    line_chart_svg,
    mf_query,
    page_shell,
    stat_tile,
)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "bi" / "executive_scorecard.html"


def latest_closed_period_row() -> dict[str, Any]:
    # Two queries, not one: net_booked_revenue/cash_collected_against_bookings
    # (sm_revenue_reconciliation) have an is_closed dimension; active_customers
    # (sm_active_customers) doesn't share that grain and mf query rejects
    # combining them in a single --group-by (confirmed empirically — this
    # is the "safe to combine" boundary from
    # docs/metric_definitions_semantic.md showing up in this script's own
    # data, not just in the reference doc). Merged here in Python instead.
    revenue_df: pd.DataFrame = mf_query(
        "net_booked_revenue,cash_collected_against_bookings",
        group_by="metric_time__month,period_id__is_closed",
    )
    closed_revenue: pd.DataFrame = revenue_df.loc[revenue_df["period_id__is_closed"]]
    latest_revenue_rows: list[dict[str, Any]] = closed_revenue.sort_values(
        "metric_time__month"
    ).to_dict(orient="records")
    latest_revenue = latest_revenue_rows[-1]

    active_customers_df: pd.DataFrame = mf_query(
        "active_customers", group_by="metric_time__month"
    )
    latest_active_rows: list[dict[str, Any]] = active_customers_df.sort_values(
        "metric_time__month"
    ).to_dict(orient="records")
    target_month = latest_revenue["metric_time__month"]
    matching_active = [r for r in latest_active_rows if r["metric_time__month"] == target_month]
    fallback = latest_active_rows[-1]["active_customers"]
    latest_revenue["active_customers"] = (
        matching_active[0]["active_customers"] if matching_active else fallback
    )
    return latest_revenue


def latest_month_row(metrics: str) -> dict[str, Any]:
    df: pd.DataFrame = mf_query(metrics, group_by="metric_time__month")
    value_columns = [c for c in df.columns if c != "metric_time__month"]
    df = df.dropna(subset=value_columns, how="all")
    sorted_df: pd.DataFrame = df.sort_values("metric_time__month")
    rows: list[dict[str, Any]] = sorted_df.to_dict(orient="records")
    return rows[-1]


def main() -> None:
    latest_period = latest_closed_period_row()
    latest_mrr = latest_month_row("mrr,churn_rate")
    retention_df: pd.DataFrame = mf_query(
        "retention_rate", group_by="retention_cohort__months_since_cohort_start"
    )
    month_1_retention: pd.DataFrame = retention_df.loc[
        retention_df["retention_cohort__months_since_cohort_start"] == 1
    ]
    retention_rows: list[dict[str, Any]] = month_1_retention.to_dict(orient="records")
    retention_value: float | None = (
        float(retention_rows[0]["retention_rate"]) if retention_rows else None
    )

    stat_tiles = "".join(
        [
            stat_tile(
                "Net booked revenue (latest closed period)",
                format_money(float(latest_period["net_booked_revenue"])),
            ),
            stat_tile(
                "Cash collected against bookings",
                format_money(float(latest_period["cash_collected_against_bookings"])),
            ),
            stat_tile(
                "Active customers", format_count(float(latest_period["active_customers"]))
            ),
            stat_tile("MRR (latest month)", format_money(float(latest_mrr["mrr"]))),
            stat_tile(
                "Churn rate (latest month)", format_percent(float(latest_mrr["churn_rate"]))
            ),
            stat_tile(
                "Month-1 retention",
                format_percent(retention_value) if retention_value is not None else "—",
            ),
        ]
    )

    # Closed periods only: the last 1-2 periods are still accumulating by
    # construction (dim_accounting_periods.is_closed), and plotting them
    # would show a misleading cliff at the end of the trend that's an
    # artifact of the period not being over yet, not a real revenue drop
    # (confirmed empirically: the open period's own value is a small
    # fraction of every closed period around it) — same reasoning Phase 5's
    # volume-anomaly check already applies to this data.
    revenue_trend: pd.DataFrame = mf_query(
        "net_booked_revenue", group_by="metric_time__month,period_id__is_closed"
    )
    revenue_trend = revenue_trend.loc[revenue_trend["period_id__is_closed"]]
    revenue_trend = revenue_trend.sort_values("metric_time__month").tail(18)
    month_labels: pd.Series = revenue_trend["metric_time__month"].astype(str).str.slice(0, 7)
    revenue_trend = revenue_trend.assign(**{"metric_time__month": month_labels})
    revenue_chart = line_chart_svg(
        revenue_trend, "metric_time__month", "net_booked_revenue", y_format=format_money
    )

    mrr_trend: pd.DataFrame = mf_query("mrr", group_by="metric_time__month")
    mrr_trend = mrr_trend.sort_values("metric_time__month").tail(18)
    mrr_trend = mrr_trend.loc[mrr_trend["mrr"] > 0]
    mrr_month_labels: pd.Series = mrr_trend["metric_time__month"].astype(str).str.slice(0, 7)
    mrr_trend = mrr_trend.assign(**{"metric_time__month": mrr_month_labels})
    mrr_chart = line_chart_svg(
        mrr_trend, "metric_time__month", "mrr", y_format=format_money, color_slot="series-3"
    )

    body = f"""
<div class="stat-row">{stat_tiles}</div>
<div class="card">
  <h2>Net booked revenue — last 18 months</h2>
  {revenue_chart}
</div>
<div class="card">
  <h2>MRR — last 18 months with subscription activity</h2>
  {mrr_chart}
</div>
<details>
  <summary>Reproduce this page</summary>
  <p>uv run python scripts/generate_executive_scorecard.py — every query above is
  <code>mf query --metrics ... --group-by ...</code>, listed in
  docs/metric_definitions_semantic.md.</p>
</details>
"""

    html = page_shell(
        "Meridian Executive Scorecard",
        datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        body,
    )
    OUTPUT_PATH.write_text(html)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
