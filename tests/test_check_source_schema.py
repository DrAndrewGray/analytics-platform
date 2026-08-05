"""Tests for the source-schema drift diff logic.

diff_schemas() is a pure function (no database needed), unlike most of this
test suite's other targets — tested directly here rather than requiring a
live Postgres, since there's nothing DB-specific about the comparison itself.
"""

from __future__ import annotations

from scripts.check_source_schema import diff_schemas


def test_identical_schemas_produce_no_findings() -> None:
    schema = {"raw.orders": {"order_id": "bigint", "status": "text"}}
    assert diff_schemas(schema, schema) == []


def test_missing_table_is_reported() -> None:
    expected = {"raw.orders": {"order_id": "bigint"}}
    live: dict[str, dict[str, str]] = {}
    findings = diff_schemas(expected, live)
    assert len(findings) == 1
    assert "MISSING TABLE: raw.orders" in findings[0]


def test_new_table_is_reported() -> None:
    expected: dict[str, dict[str, str]] = {}
    live = {"raw.orders": {"order_id": "bigint"}}
    findings = diff_schemas(expected, live)
    assert len(findings) == 1
    assert "NEW TABLE: raw.orders" in findings[0]


def test_missing_column_is_reported() -> None:
    expected = {"raw.orders": {"order_id": "bigint", "channel": "text"}}
    live = {"raw.orders": {"order_id": "bigint"}}
    findings = diff_schemas(expected, live)
    assert len(findings) == 1
    assert "MISSING COLUMN: raw.orders.channel" in findings[0]


def test_new_column_is_reported() -> None:
    expected = {"raw.orders": {"order_id": "bigint"}}
    live = {"raw.orders": {"order_id": "bigint", "channel": "text"}}
    findings = diff_schemas(expected, live)
    assert len(findings) == 1
    assert "NEW COLUMN: raw.orders.channel" in findings[0]


def test_type_change_is_reported() -> None:
    expected = {"raw.orders": {"order_id": "bigint"}}
    live = {"raw.orders": {"order_id": "text"}}
    findings = diff_schemas(expected, live)
    assert len(findings) == 1
    assert "TYPE CHANGED: raw.orders.order_id (bigint -> text)" in findings[0]


def test_multiple_findings_are_all_reported() -> None:
    expected = {
        "raw.orders": {"order_id": "bigint", "channel": "text"},
        "raw.products": {"product_id": "bigint"},
    }
    live = {
        "raw.orders": {"order_id": "text"},
        "raw.customers": {"customer_id": "bigint"},
    }
    findings = diff_schemas(expected, live)
    assert len(findings) == 4
