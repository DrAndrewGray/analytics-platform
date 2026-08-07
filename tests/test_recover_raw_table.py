"""Tests for scripts/recover_raw_table.py's approved-table allowlist.

This script runs DDL (DROP TABLE ... CASCADE) against a table named by a
CLI argument — APPROVED_TABLES (and argparse's `choices` enforcement of
it) is what stands between that and dropping an arbitrary table, so it's
tested directly rather than only exercised end-to-end against a live
database.
"""

from __future__ import annotations

import subprocess
import sys

from scripts.recover_raw_table import APPROVED_TABLES


def test_approved_tables_cover_every_ingested_raw_table() -> None:
    assert APPROVED_TABLES == {
        "raw.customers",
        "raw.products",
        "raw.orders",
        "raw.order_items",
        "raw.payments",
        "raw_billing.plans",
        "raw_billing.subscriptions",
        "raw_billing.invoices",
        "raw_billing.invoice_lines",
        "raw_billing.payments",
        "raw_billing.refunds",
        "raw_events.events",
    }


def test_cli_rejects_a_table_outside_the_allowlist() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.recover_raw_table", "analytics_marts.fct_orders"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_cli_rejects_sql_injection_attempt() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.recover_raw_table",
            "raw.orders CASCADE; DROP TABLE analytics_marts.fct_orders",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "invalid choice" in result.stderr
