"""Detect source-schema drift: compare live raw tables against a checked-in snapshot.

dbt's contract primitive is model-level (see docs/data_contracts.md) — there's
no dbt-native way to say "fail if raw.orders loses a column." This script is
the practical equivalent for raw sources: it queries information_schema for
every table across the three raw schemas, diffs the result against
docs/expected_source_schemas.json, and reports exactly what changed before
dbt build ever runs, rather than surfacing as a buried compilation error
partway through a model.

Usage:
    uv run python scripts/check_source_schema.py            # compare, exit 1 on drift
    uv run python scripts/check_source_schema.py --update    # regenerate the snapshot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "docs" / "expected_source_schemas.json"

RAW_SCHEMAS = ["raw", "raw_billing", "raw_events"]


def get_engine() -> Engine:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "meridian")
    user = os.getenv("POSTGRES_USER", "meridian")
    password = os.getenv("POSTGRES_PASSWORD", "meridian")
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    return create_engine(url)


def fetch_live_schema(engine: Engine) -> dict[str, dict[str, str]]:
    """Return {"schema.table": {"column_name": "data_type", ...}} for every raw table."""
    query = text(
        """
        select table_schema, table_name, column_name, data_type
        from information_schema.columns
        where table_schema = any(:schemas)
        order by table_schema, table_name, ordinal_position
        """
    )
    live: dict[str, dict[str, str]] = {}
    with engine.connect() as conn:
        rows = conn.execute(query, {"schemas": RAW_SCHEMAS}).fetchall()
    for schema, table, column, data_type in rows:
        key = f"{schema}.{table}"
        live.setdefault(key, {})[column] = data_type
    return live


def load_snapshot() -> dict[str, dict[str, str]]:
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text())


def save_snapshot(schema: dict[str, dict[str, str]]) -> None:
    SNAPSHOT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


def diff_schemas(
    expected: dict[str, dict[str, str]], live: dict[str, dict[str, str]]
) -> list[str]:
    """Return a list of human-readable diff lines; empty means no drift."""
    findings: list[str] = []

    missing_tables = sorted(set(expected) - set(live))
    added_tables = sorted(set(live) - set(expected))
    for table in missing_tables:
        findings.append(f"MISSING TABLE: {table} (present in snapshot, not in database)")
    for table in added_tables:
        findings.append(f"NEW TABLE: {table} (present in database, not in snapshot)")

    for table in sorted(set(expected) & set(live)):
        expected_cols = expected[table]
        live_cols = live[table]

        missing_cols = sorted(set(expected_cols) - set(live_cols))
        added_cols = sorted(set(live_cols) - set(expected_cols))
        for col in missing_cols:
            findings.append(f"MISSING COLUMN: {table}.{col} (expected {expected_cols[col]})")
        for col in added_cols:
            findings.append(f"NEW COLUMN: {table}.{col} ({live_cols[col]})")

        for col in sorted(set(expected_cols) & set(live_cols)):
            if expected_cols[col] != live_cols[col]:
                findings.append(
                    f"TYPE CHANGED: {table}.{col} "
                    f"({expected_cols[col]} -> {live_cols[col]})"
                )

    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate the snapshot from the live database instead of comparing against it.",
    )
    args = parser.parse_args()

    engine = get_engine()
    live = fetch_live_schema(engine)

    if not live:
        print(f"No tables found across schemas {RAW_SCHEMAS} — is Postgres running and seeded?")
        sys.exit(1)

    if args.update:
        save_snapshot(live)
        table_count = len(live)
        print(f"Wrote {SNAPSHOT_PATH} ({table_count} tables).")
        return

    expected = load_snapshot()
    if not expected:
        print(f"No snapshot at {SNAPSHOT_PATH} yet. Run with --update to create one.")
        sys.exit(1)

    findings = diff_schemas(expected, live)
    if not findings:
        print(f"OK: live schema matches {SNAPSHOT_PATH} ({len(live)} tables).")
        return

    print(f"SOURCE SCHEMA DRIFT DETECTED ({len(findings)} finding(s)):")
    for finding in findings:
        print(f"  - {finding}")
    sys.exit(1)


if __name__ == "__main__":
    main()
