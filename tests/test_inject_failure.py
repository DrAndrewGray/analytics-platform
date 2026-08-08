"""Tests for scripts/inject_failure.py's target-agnostic period-close logic.

_latest_closed_period_end_date() used to be a SQL join against
analytics_seeds.accounting_periods -- a dbt-*built* table that only exists
if the dev target has been built. The reliability-demo workflow only ever
builds `ci` (analytics_ci_seeds), so that query failed outright the first
time this scenario actually ran in GitHub Actions rather than on a local
dev machine that happened to already have `dev` built too. Fixed by
reading the checked-in seed CSV directly, tested here against the real
file rather than a fixture, since the whole point is agreement with what
actually ships.
"""

from __future__ import annotations

import pandas as pd

from scripts.inject_failure import SEEDS_DIR, _latest_closed_period_end_date


def test_matches_the_real_seed_file_directly() -> None:
    periods = pd.read_csv(SEEDS_DIR / "accounting_periods.csv")
    closed = periods[periods["closed_at"].notna()]
    expected = str(closed["period_end_date"].max())

    assert _latest_closed_period_end_date() == expected


def test_result_is_a_period_end_date_with_a_non_null_closed_at() -> None:
    periods = pd.read_csv(SEEDS_DIR / "accounting_periods.csv")
    result = _latest_closed_period_end_date()

    matching_row = periods[periods["period_end_date"] == result].iloc[0]
    assert pd.notna(matching_row["closed_at"])


def test_open_periods_are_excluded() -> None:
    """The seed keeps its most recent periods open (closed_at is blank) —
    the result must never be one of those, even though they sort later."""
    periods = pd.read_csv(SEEDS_DIR / "accounting_periods.csv")
    open_period_ends = set(periods.loc[periods["closed_at"].isna(), "period_end_date"])

    assert _latest_closed_period_end_date() not in open_period_ends
