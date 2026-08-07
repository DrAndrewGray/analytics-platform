"""Tests for scripts/generate_alert_report.py's scenario-assertion logic.

check_scenario() is a pure function (no database, no dbt artifacts needed)
— tested directly against constructed alert dicts rather than requiring a
live dbt run, unlike most of what this file checks.
"""

from __future__ import annotations

from scripts.generate_alert_report import check_scenario


def _alert(failure_count: int, names: list[str], late_adjustments: int | None = 0) -> dict:
    return {
        "failure_count": failure_count,
        "findings": [{"name": name} for name in names],
        "late_adjustments": (
            None
            if late_adjustments is None
            else [{"refund_id": i} for i in range(late_adjustments)]
        ),
    }


def test_matching_failure_passes() -> None:
    passed, _ = check_scenario("drop-column", _alert(1, ["stg_orders"]))
    assert passed


def test_unrelated_failure_does_not_pass() -> None:
    """The whole point of --assert-scenario: a build failure alone isn't enough."""
    passed, _ = check_scenario("drop-column", _alert(1, ["some_unrelated_test"]))
    assert not passed


def test_no_failure_does_not_pass_for_a_failure_expecting_scenario() -> None:
    passed, _ = check_scenario("drop-column", _alert(0, []))
    assert not passed


def test_unregistered_scenario_does_not_pass() -> None:
    passed, message = check_scenario("not-a-real-scenario", _alert(0, []))
    assert not passed
    assert "No expectation registered" in message


def test_clean_build_passes_for_late_arriving_refund_without_baseline() -> None:
    passed, _ = check_scenario("late-arriving-refund", _alert(0, [], late_adjustments=1))
    assert passed


def test_failed_build_does_not_pass_for_late_arriving_refund() -> None:
    passed, _ = check_scenario("late-arriving-refund", _alert(1, ["something"]))
    assert not passed


def test_baseline_requires_the_count_to_have_grown() -> None:
    """A clean build with an unchanged late_adjustments count must fail:
    the scenario is supposed to add exactly one new late adjustment."""
    passed, message = check_scenario(
        "late-arriving-refund",
        _alert(0, [], late_adjustments=1),
        baseline_late_adjustments=1,
    )
    assert not passed
    assert "still 1" in message


def test_baseline_passes_once_the_count_grows() -> None:
    passed, _ = check_scenario(
        "late-arriving-refund",
        _alert(0, [], late_adjustments=2),
        baseline_late_adjustments=1,
    )
    assert passed


def test_baseline_fails_closed_when_database_unreachable() -> None:
    """late_adjustments is None when fetch_late_adjustments() couldn't reach the
    database — that must be a failure, not a silent skip, when a baseline was
    explicitly requested (the caller wants this specific thing verified)."""
    passed, message = check_scenario(
        "late-arriving-refund",
        _alert(0, [], late_adjustments=None),
        baseline_late_adjustments=1,
    )
    assert not passed
    assert "wasn't reachable" in message
