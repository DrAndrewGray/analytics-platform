"""Tests for scripts/recover_raw_table.py's table-name validation.

This script runs DDL (DROP TABLE ... CASCADE) built from a CLI argument —
_TABLE_PATTERN is what stands between that and interpolating arbitrary
input into a SQL statement, so it's tested directly rather than only
exercised end-to-end against a live database.
"""

from __future__ import annotations

import pytest

from scripts.recover_raw_table import _TABLE_PATTERN


@pytest.mark.parametrize(
    "table",
    ["raw.orders", "raw_billing.invoices", "raw_events.events", "a.b", "_x.y_1"],
)
def test_valid_schema_table_names_match(table: str) -> None:
    assert _TABLE_PATTERN.match(table)


@pytest.mark.parametrize(
    "table",
    [
        "raw.orders CASCADE; DROP TABLE analytics_marts.fct_orders",
        "raw.orders; DROP SCHEMA raw",
        "raw..orders",
        "raw",
        "raw.orders.extra",
        "raw.'orders'",
        "",
        "raw .orders",
    ],
)
def test_invalid_input_is_rejected(table: str) -> None:
    assert _TABLE_PATTERN.match(table) is None
