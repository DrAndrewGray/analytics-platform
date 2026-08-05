"""Turn a dbt run's results into one structured alert instead of a scrollback of logs.

Reads dbt/target/run_results.json (written by the most recent `dbt build`/
`dbt test`) and dbt/target/manifest.json, finds every failed/errored node,
and — reusing the same downstream-closure logic as impact_analysis.py —
reports what's actually affected: for a failed test, which model it was
testing and what's downstream of that model; for a failed model, what's
downstream of it directly. This is the "so what do I actually look at"
question a raw dbt failure log doesn't answer on its own.

Usage:
    uv run python scripts/generate_alert_report.py                # human-readable
    uv run python scripts/generate_alert_report.py --json          # structured JSON to stdout
    uv run python scripts/generate_alert_report.py --output f.json # also write JSON to a file

Also queries the live database (if reachable) for currently-open late
period-close adjustments (fct_period_close_adjustments.is_late_adjustment)
and reports them as informational, not failures — a late adjustment is
normal, tracked activity per docs/metric_definitions_finance.md, not a bug,
but it's exactly the kind of thing worth surfacing in an alert rather than
requiring someone to remember to go query for it.

Exit code is 1 if any failures were found, 0 otherwise — safe to use as a
CI gate on its own, though `dbt build`'s own exit code already does that;
this script is about *reporting* the failure, not detecting it. The
informational section never affects the exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

from scripts.impact_analysis import downstream_closure, summarize
from scripts.ingest import get_engine

TARGET_DIR = Path(__file__).resolve().parent.parent / "dbt" / "target"
RUN_RESULTS_PATH = TARGET_DIR / "run_results.json"
MANIFEST_PATH = TARGET_DIR / "manifest.json"

FAILED_STATUSES = {"fail", "error"}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"No {path.name} at {path}. Run `dbt build` from the dbt/ directory first.")
        sys.exit(1)
    return json.loads(path.read_text())


def _node_name(manifest: dict[str, Any], unique_id: str) -> str:
    if unique_id in manifest["nodes"]:
        return manifest["nodes"][unique_id]["name"]
    if unique_id in manifest["exposures"]:
        return manifest["exposures"][unique_id]["name"]
    return unique_id


def _tested_model_id(manifest: dict[str, Any], test_unique_id: str) -> str | None:
    """A test's own depends_on.nodes points at the model(s) it tests."""
    node = manifest["nodes"].get(test_unique_id, {})
    depends_on = node.get("depends_on", {}).get("nodes", [])
    model_ids = [n for n in depends_on if n.startswith("model.")]
    return model_ids[0] if model_ids else None


def build_alert(manifest: dict[str, Any], run_results: dict[str, Any]) -> dict[str, Any]:
    failures = [r for r in run_results["results"] if r["status"] in FAILED_STATUSES]

    findings = []
    for failure in failures:
        unique_id = failure["unique_id"]
        node = manifest["nodes"].get(unique_id, {})
        resource_type = node.get("resource_type", "unknown")
        name = _node_name(manifest, unique_id)

        impact_source_id = unique_id
        if resource_type == "test":
            tested_model_id = _tested_model_id(manifest, unique_id)
            impact_source_id = tested_model_id or unique_id

        downstream_ids = downstream_closure(manifest, impact_source_id)
        downstream_groups = summarize(manifest, downstream_ids)

        findings.append(
            {
                "unique_id": unique_id,
                "resource_type": resource_type,
                "name": name,
                "status": failure["status"],
                "message": failure.get("message"),
                "downstream_models": downstream_groups.get("model", []),
                "downstream_test_count": len(downstream_groups.get("test", [])),
                "downstream_exposures": downstream_groups.get("exposure", []),
            }
        )

    return {
        "failure_count": len(findings),
        "findings": findings,
    }


def fetch_late_adjustments() -> list[dict[str, Any]] | None:
    """Currently-open late period-close adjustments, or None if the DB isn't reachable."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT refund_id, original_period_id, adjustment_period_id, days_after_close
                    FROM analytics_marts.fct_period_close_adjustments
                    WHERE is_late_adjustment
                    ORDER BY days_after_close DESC
                    """
                )
            ).fetchall()
    except Exception:
        return None
    return [
        {
            "refund_id": row.refund_id,
            "original_period_id": row.original_period_id,
            "adjustment_period_id": row.adjustment_period_id,
            "days_after_close": row.days_after_close,
        }
        for row in rows
    ]


def print_human_readable(alert: dict[str, Any]) -> None:
    if alert["failure_count"] == 0:
        print("OK: no failures in the most recent dbt run.")
    else:
        print(f"ALERT: {alert['failure_count']} failure(s) in the most recent dbt run.")
        for finding in alert["findings"]:
            print()
            print(f"[{finding['resource_type'].upper()}] {finding['name']} — {finding['status']}")
            if finding["message"]:
                print(f"  message: {finding['message']}")
            if finding["downstream_models"]:
                print(f"  downstream models ({len(finding['downstream_models'])}):")
                for model_name in finding["downstream_models"]:
                    print(f"    - {model_name}")
            if finding["downstream_test_count"]:
                print(f"  downstream tests affected: {finding['downstream_test_count']}")
            if finding["downstream_exposures"]:
                print(f"  downstream exposures: {', '.join(finding['downstream_exposures'])}")

    late_adjustments = alert.get("late_adjustments")
    if late_adjustments is None:
        return
    print()
    if not late_adjustments:
        print("INFO: no open late period-close adjustments.")
        return
    print(f"INFO: {len(late_adjustments)} open late period-close adjustment(s) (not a failure):")
    for adj in late_adjustments:
        print(
            f"  - refund_id={adj['refund_id']}: booked in period "
            f"{adj['original_period_id']}, landed in period "
            f"{adj['adjustment_period_id']} ({adj['days_after_close']} days after close)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print structured JSON to stdout.")
    parser.add_argument("--output", type=Path, help="Also write the JSON alert to this path.")
    args = parser.parse_args()

    manifest = load_json(MANIFEST_PATH)
    run_results = load_json(RUN_RESULTS_PATH)
    alert = build_alert(manifest, run_results)
    alert["late_adjustments"] = fetch_late_adjustments()

    if args.json:
        print(json.dumps(alert, indent=2))
    else:
        print_human_readable(alert)

    if args.output:
        args.output.write_text(json.dumps(alert, indent=2) + "\n")
        print(f"\nWrote {args.output}")

    sys.exit(1 if alert["failure_count"] > 0 else 0)


if __name__ == "__main__":
    main()
