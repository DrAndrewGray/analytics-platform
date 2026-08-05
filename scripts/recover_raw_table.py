"""Drop a raw table (CASCADE), for schema-shaped failures re-ingestion alone can't fix.

scripts/ingest.py truncates and re-inserts into the *existing* table by
design — correct for a normal data refresh, but it can't repair a table
whose structure itself is wrong (a dropped column, a changed type). This
is the other half of recovering from scripts/inject_failure.py's
drop-column / change-column-type scenarios: drop the table structurally,
then re-run the matching ingest*.py script so pandas' to_sql() recreates
it fresh. CASCADE unconditionally, not a plain DROP TABLE — a `dbt build`
run in between injecting and recovering can recreate a dependent view
against the broken structure, which then blocks a plain DROP TABLE (see
docs/incidents/002_column_type_change.md).

Usage:
    uv run python scripts/recover_raw_table.py raw.orders
"""

from __future__ import annotations

import argparse
import re

from dotenv import load_dotenv
from sqlalchemy import text

from scripts.ingest import get_engine

load_dotenv()

# schema.table only, both simple identifiers — this drops a table by name
# built from CLI input, so reject anything that isn't exactly that shape
# rather than interpolating an arbitrary argument into DDL.
_TABLE_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", help="schema.table to drop, e.g. raw.orders")
    args = parser.parse_args()

    if not _TABLE_PATTERN.match(args.table):
        raise SystemExit(f"'{args.table}' doesn't look like schema.table — refusing to run DDL.")

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {args.table} CASCADE"))
    print(f"Dropped {args.table} (CASCADE). Re-run the matching ingest*.py script to recreate it.")


if __name__ == "__main__":
    main()
