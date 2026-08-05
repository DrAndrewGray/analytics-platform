"""Generate docs/data_health_report.md: a point-in-time snapshot of warehouse health.

Combines three sources: dbt/target/run_results.json (test pass/fail counts,
from the most recent `dbt build`/`dbt test`), dbt/target/sources.json
(freshness status, from the most recent `dbt source freshness`), and a
couple of direct queries against the live warehouse for state that isn't
captured in either artifact (volume anomalies, open late adjustments).

This is a generated file, not a live dashboard — see
docs/reliability_strategy.md for why. Regenerate it after any `dbt build`:

    uv run python scripts/generate_health_report.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from scripts.generate_alert_report import fetch_late_adjustments
from scripts.ingest import get_engine

TARGET_DIR = Path(__file__).resolve().parent.parent / "dbt" / "target"
RUN_RESULTS_PATH = TARGET_DIR / "run_results.json"
SOURCES_PATH = TARGET_DIR / "sources.json"
MANIFEST_PATH = TARGET_DIR / "manifest.json"
REPORT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data_health_report.md"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def summarize_tests(
    run_results: dict[str, Any] | None, manifest: dict[str, Any] | None
) -> dict[str, int]:
    """Status counts for test nodes specifically, not every node run_results.json covers.

    run_results.json mixes models, seeds, snapshots, and tests in one list, and
    models report status='success' while tests report 'pass'/'fail'/'warn'/'error' —
    counting every node's status without filtering to resource_type == 'test' first
    would silently fold model results into what's presented as a test summary.
    """
    if run_results is None or manifest is None:
        return {}
    counts: dict[str, int] = {}
    for result in run_results["results"]:
        node = manifest["nodes"].get(result["unique_id"], {})
        if node.get("resource_type") != "test":
            continue
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return counts


def summarize_freshness(sources: dict[str, Any] | None) -> list[dict[str, Any]]:
    if sources is None:
        return []
    return [
        {"name": r["unique_id"].split(".")[-1], "status": r["status"]}
        for r in sources["results"]
    ]


def contracted_models(manifest: dict[str, Any] | None) -> list[str]:
    if manifest is None:
        return []
    return sorted(
        node["name"]
        for node in manifest["nodes"].values()
        if node.get("contract", {}).get("enforced")
    )


def fetch_volume_anomalies() -> list[dict[str, Any]] | None:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT source_name, period_id, period_start_date, pct_change_vs_trailing_avg
                    FROM analytics_marts.mart_volume_anomalies
                    WHERE is_anomaly
                    ORDER BY period_id DESC
                    """
                )
            ).fetchall()
    except Exception:
        return None
    return [
        {
            "source_name": row.source_name,
            "period_id": row.period_id,
            "period_start_date": str(row.period_start_date),
            "pct_change": row.pct_change_vs_trailing_avg,
        }
        for row in rows
    ]


def render_report(
    generated_at: str,
    test_counts: dict[str, int],
    freshness: list[dict[str, Any]],
    contracts: list[str],
    volume_anomalies: list[dict[str, Any]] | None,
    late_adjustments: list[dict[str, Any]] | None,
) -> str:
    lines = [
        "# Data health report",
        "",
        f"Generated {generated_at} by `scripts/generate_health_report.py`. "
        "This is a point-in-time snapshot, not a live dashboard — regenerate "
        "after any `dbt build` / `dbt source freshness` run. See "
        "docs/reliability_strategy.md for why this is a file, not a service.",
        "",
        "## Tests",
        "",
    ]
    if test_counts:
        for status in ["pass", "fail", "error", "warn", "skipped"]:
            if status in test_counts:
                lines.append(f"- **{status}**: {test_counts[status]}")
    else:
        lines.append("No run_results.json found — run `dbt build` first.")
    lines.append("")

    lines.append("## Source freshness")
    lines.append("")
    if freshness:
        non_pass = [f for f in freshness if f["status"] != "pass"]
        lines.append(f"{len(freshness)} sources checked, {len(non_pass)} not passing.")
        for f in non_pass:
            lines.append(f"- **{f['name']}**: {f['status']}")
    else:
        lines.append("No sources.json found — run `dbt source freshness` first.")
    lines.append("")

    lines.append("## Contracted models")
    lines.append("")
    if contracts:
        for name in contracts:
            lines.append(f"- {name}")
    else:
        lines.append("No manifest.json found, or no contracted models.")
    lines.append("")

    lines.append("## Volume anomalies")
    lines.append("")
    if volume_anomalies is None:
        lines.append("Database not reachable — skipped.")
    elif not volume_anomalies:
        lines.append("None.")
    else:
        for a in volume_anomalies:
            lines.append(
                f"- **{a['source_name']}**, period {a['period_id']} "
                f"({a['period_start_date']}): {a['pct_change']}% vs. trailing average"
            )
    lines.append("")

    lines.append("## Open late period-close adjustments")
    lines.append("")
    if late_adjustments is None:
        lines.append("Database not reachable — skipped.")
    elif not late_adjustments:
        lines.append("None.")
    else:
        for adj in late_adjustments:
            lines.append(
                f"- refund_id={adj['refund_id']}: booked in period "
                f"{adj['original_period_id']}, landed in period "
                f"{adj['adjustment_period_id']} ({adj['days_after_close']} days after close)"
            )
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    manifest = load_json(MANIFEST_PATH)
    run_results = load_json(RUN_RESULTS_PATH)
    sources = load_json(SOURCES_PATH)

    report = render_report(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        test_counts=summarize_tests(run_results, manifest),
        freshness=summarize_freshness(sources),
        contracts=contracted_models(manifest),
        volume_anomalies=fetch_volume_anomalies(),
        late_adjustments=fetch_late_adjustments(),
    )
    REPORT_PATH.write_text(report + "\n")
    print(f"Wrote {REPORT_PATH}")

    if run_results is None or sources is None:
        print(
            "Note: run `dbt build` and `dbt source freshness` first for a complete report.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
