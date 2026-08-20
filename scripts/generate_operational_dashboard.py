"""Generate docs/bi/operational_dashboard.html — drill-down views, one page.

Same rule as the executive scorecard: every number comes from
scripts/bi_common.mf_query() (`mf query` under the hood), never a
hand-written SQL aggregate. This is the operational counterpart —
channel/region/funnel/cohort breakdowns an executive scorecard wouldn't
carry, using the exact same metric definitions.

Usage:
    uv run python scripts/generate_operational_dashboard.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.bi_common import (
    bar_chart_svg,
    format_count,
    format_money,
    format_percent,
    line_chart_svg,
    mf_query,
    page_shell,
)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "bi" / "operational_dashboard.html"


def revenue_by_channel_card() -> str:
    df: pd.DataFrame = mf_query(
        "order_revenue",
        group_by="order_id__order_channel",
        where="{{ Dimension('order_id__order_status') }} = 'completed'",
    )
    rows: list[dict[str, Any]] = df.sort_values("order_revenue", ascending=False).to_dict(
        orient="records"
    )
    labels = [str(r["order_id__order_channel"]) for r in rows]
    values = [float(r["order_revenue"]) for r in rows]
    chart = bar_chart_svg(labels, values, y_format=format_money, color_slot="series-1")
    return f"""<div class="card">
  <h2>Completed order revenue by channel (all-time)</h2>
  {chart}
</div>"""


def active_customers_by_region_card() -> str:
    df: pd.DataFrame = mf_query("active_customers", group_by="customer_id__region")
    top: pd.DataFrame = df.sort_values("active_customers", ascending=False).head(10)
    rows: list[dict[str, Any]] = top.to_dict(orient="records")
    labels = [str(r["customer_id__region"]) for r in rows]
    values = [float(r["active_customers"]) for r in rows]
    chart = bar_chart_svg(
        labels, values, y_format=format_count, color_slot="series-3", horizontal=True, height=320
    )
    return f"""<div class="card">
  <h2>Top 10 regions by active customers (all-time)</h2>
  {chart}
</div>"""


def funnel_card() -> str:
    df: pd.DataFrame = mf_query("viewers,carters,checkout_starters,purchasers")
    rows: list[dict[str, Any]] = df.to_dict(orient="records")
    row = rows[0]
    labels = ["Viewers", "Carters", "Checkout starters", "Purchasers"]
    values = [
        float(row["viewers"]),
        float(row["carters"]),
        float(row["checkout_starters"]),
        float(row["purchasers"]),
    ]
    chart = bar_chart_svg(labels, values, y_format=format_count, color_slot="series-2")
    return f"""<div class="card">
  <h2>Same-day funnel presence (all-time totals)</h2>
  <p style="font-size:0.8125rem;color:var(--text-secondary);margin:-8px 0 16px;">
    Same-day presence, not a sequential funnel — a purchaser counts even if their
    view/cart/checkout that day weren't of the same item. See
    docs/metric_definitions_events.md.
  </p>
  {chart}
</div>"""


def retention_card() -> str:
    df: pd.DataFrame = mf_query(
        "retention_rate", group_by="retention_cohort__months_since_cohort_start"
    )
    df = df.sort_values("retention_cohort__months_since_cohort_start")
    df = df.rename(columns={"retention_cohort__months_since_cohort_start": "months_since"})
    chart = line_chart_svg(
        df, "months_since", "retention_rate", y_format=format_percent, color_slot="series-4"
    )
    return f"""<div class="card">
  <h2>Subscription retention curve, by months since cohort start</h2>
  {chart}
</div>"""


def main() -> None:
    body = "\n".join(
        [
            revenue_by_channel_card(),
            active_customers_by_region_card(),
            funnel_card(),
            retention_card(),
            """<details>
  <summary>Reproduce this page</summary>
  <p>uv run python scripts/generate_operational_dashboard.py — every query above
  is <code>mf query --metrics ... --group-by ...</code>, listed in
  docs/metric_definitions_semantic.md.</p>
</details>""",
        ]
    )
    html = page_shell(
        "Meridian Operational Dashboard",
        datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        body,
    )
    OUTPUT_PATH.write_text(html)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
