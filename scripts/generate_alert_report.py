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
    uv run python scripts/generate_alert_report.py --assert-scenario drop-column
        # exits 1 unless the SPECIFIC node scripts/inject_failure.py's
        # drop-column scenario is expected to break actually appears
        # among the failures (or, for scenarios expected to stay green,
        # unless the run is actually clean) — see SCENARIO_EXPECTATIONS,
        # below. Used by .github/workflows/reliability-demo.yml so the
        # demo proves the *right* control fired, not just that
        # something, anything, failed.
    uv run python scripts/generate_alert_report.py --assert-scenario late-arriving-refund \
        --baseline-late-adjustments 1
        # for the one scenario that's expected to stay green: also
        # requires the informational late_adjustments section to have
        # grown past the given baseline count, not just "the build
        # didn't fail" — a bug in fetch_late_adjustments() itself, or in
        # is_late_adjustment upstream, would otherwise pass silently.

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
from sqlalchemy.engine import Engine

from scripts.impact_analysis import downstream_closure, summarize
from scripts.ingest import get_engine

# dbt builds marts under a schema name that depends on which target built
# them (see dbt/profiles.yml): `analytics_marts` for `dev`,
# `analytics_ci_marts` for `ci`. A script that queries a mart directly has
# no business assuming either — resolve_marts_schema() below checks which
# one actually exists instead. (This is the same class of bug
# scripts/inject_failure.py's late-arriving-refund scenario had: it worked
# on every local dev machine, which always had `dev` built from unrelated
# earlier work, and failed the first time it ran in a `ci`-only
# environment — see docs/incidents/ and the README's "Bugs this caught.")
MARTS_SCHEMAS = ("analytics_marts", "analytics_ci_marts")

TARGET_DIR = Path(__file__).resolve().parent.parent / "dbt" / "target"
RUN_RESULTS_PATH = TARGET_DIR / "run_results.json"
MANIFEST_PATH = TARGET_DIR / "manifest.json"

FAILED_STATUSES = {"fail", "error"}

# One entry per scripts/inject_failure.py scenario that's expected to show up
# as a dbt build/test failure (source-stale is freshness-based, checked
# separately in the reliability-demo workflow — see docs/runbook.md for why
# that's a different artifact/command entirely). name_contains is matched
# against a failing finding's `name` field; picked from what each scenario
# actually produced when run for real — see docs/incidents/.
SCENARIO_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "drop-column": {"expect_failure": True, "name_contains": "stg_orders"},
    "change-column-type": {"expect_failure": True, "name_contains": "fct_orders"},
    "bad-status": {"expect_failure": True, "name_contains": "order_status"},
    "duplicate-pk": {"expect_failure": True, "name_contains": "unique_stg_orders_order_id"},
    "broken-fk": {"expect_failure": True, "name_contains": "order_items_order_id"},
    "volume-drop": {"expect_failure": True, "name_contains": "assert_no_volume_anomaly"},
    "revenue-spike": {
        "expect_failure": True,
        "name_contains": "not_implausibly_large_fct_orders_order_amount",
    },
    "late-arriving-refund": {"expect_failure": False},
}


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


def resolve_schema(engine: Engine, table: str, candidate_schemas: tuple[str, ...]) -> str | None:
    """Which of candidate_schemas actually contains `table`, or None if none do.

    Earlier entries in candidate_schemas win when more than one contains
    the table — callers order their tuple dev-target-first, since a human
    running this locally almost always wants their own dev-target data
    over a leftover ci build sitting in the same database.
    """
    with engine.connect() as conn:
        found = {
            row[0]
            for row in conn.execute(
                text(
                    "select table_schema from information_schema.tables "
                    "where table_schema = any(:schemas) and table_name = :table"
                ),
                {"schemas": list(candidate_schemas), "table": table},
            )
        }
    for schema in candidate_schemas:
        if schema in found:
            return schema
    return None


def resolve_marts_schema(engine: Engine, table: str) -> str | None:
    """Which of MARTS_SCHEMAS (analytics_marts / analytics_ci_marts) has `table`."""
    return resolve_schema(engine, table, MARTS_SCHEMAS)


def fetch_late_adjustments() -> list[dict[str, Any]] | None:
    """Currently-open late period-close adjustments, or None if the DB/table isn't reachable."""
    try:
        engine = get_engine()
        schema = resolve_marts_schema(engine, "fct_period_close_adjustments")
        if schema is None:
            return None
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT refund_id, original_period_id, adjustment_period_id, days_after_close
                    FROM {schema}.fct_period_close_adjustments
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


def check_scenario(
    scenario: str, alert: dict[str, Any], baseline_late_adjustments: int | None = None
) -> tuple[bool, str]:
    """Did the SPECIFIC control this scenario is supposed to trip actually fire?

    Deliberately stricter than "did the build fail": an unrelated failure
    (a flaky test, a different regression) would satisfy a plain
    build-outcome check without the scenario's own control having done
    anything at all. For late-arriving-refund specifically, "the build
    stayed green" isn't enough either — a bug in fetch_late_adjustments()
    or in is_late_adjustment upstream could make the new adjustment
    silently fail to show up while the build stays green for an unrelated
    reason (nothing broke because nothing ran). --baseline-late-adjustments
    closes that gap by requiring the informational count to have actually
    grown, not just checking that it's non-negative.
    """
    expectation = SCENARIO_EXPECTATIONS.get(scenario)
    if expectation is None:
        return False, f"No expectation registered for scenario '{scenario}'."

    if not expectation["expect_failure"]:
        if alert["failure_count"] != 0:
            return False, (
                f"'{scenario}' expected a clean build, but {alert['failure_count']} "
                "failure(s) were found."
            )
        if baseline_late_adjustments is None:
            return True, f"'{scenario}' expected a clean build, and got one."

        late_adjustments = alert.get("late_adjustments")
        if late_adjustments is None:
            return False, (
                f"'{scenario}' expected the late_adjustments count to grow past "
                f"{baseline_late_adjustments}, but the database wasn't reachable "
                "to check it."
            )
        current = len(late_adjustments)
        if current > baseline_late_adjustments:
            return True, (
                f"'{scenario}' expected a clean build with a new late adjustment, "
                f"and got one: late_adjustments count went from "
                f"{baseline_late_adjustments} to {current}."
            )
        return False, (
            f"'{scenario}' expected the late_adjustments count to grow past "
            f"{baseline_late_adjustments}, but it's still {current} — the build "
            "stayed green, but no new late adjustment actually showed up."
        )

    name_contains = expectation["name_contains"]
    matches = [f for f in alert["findings"] if name_contains in f["name"]]
    if matches:
        matched_names = ", ".join(f["name"] for f in matches)
        return True, f"'{scenario}' expected a failure matching '{name_contains}': {matched_names}."
    return False, (
        f"'{scenario}' expected a failure matching '{name_contains}', but none of "
        f"the {alert['failure_count']} failure(s) found matched: "
        f"{[f['name'] for f in alert['findings']]}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print structured JSON to stdout.")
    parser.add_argument("--output", type=Path, help="Also write the JSON alert to this path.")
    parser.add_argument(
        "--assert-scenario",
        choices=sorted(SCENARIO_EXPECTATIONS),
        help="Exit 1 unless this scenario's specific expected control fired.",
    )
    parser.add_argument(
        "--baseline-late-adjustments",
        type=int,
        help=(
            "Late-adjustment count captured before injecting late-arriving-refund; "
            "required alongside it to confirm the count actually grew, not just "
            "that the build stayed green. Ignored for every other scenario."
        ),
    )
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

    if args.assert_scenario:
        passed, message = check_scenario(
            args.assert_scenario, alert, args.baseline_late_adjustments
        )
        print(f"\n{'PASS' if passed else 'FAIL'}: {message}")
        sys.exit(0 if passed else 1)

    sys.exit(1 if alert["failure_count"] > 0 else 0)


if __name__ == "__main__":
    main()
