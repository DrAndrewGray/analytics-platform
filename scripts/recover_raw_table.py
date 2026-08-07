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

from dotenv import load_dotenv
from sqlalchemy import text

import scripts.ingest as ingest
import scripts.ingest_billing as ingest_billing
import scripts.ingest_events as ingest_events
from scripts.ingest import get_engine

load_dotenv()

# Built from the same TABLES/RAW_SCHEMA constants the ingest scripts
# themselves use, not a separately-maintained list — this script runs real
# DDL (DROP TABLE ... CASCADE) from a CLI argument, so it only ever
# touches a table ingestion actually owns and can recreate, never an
# arbitrary identifier that happens to be shaped like schema.table (a
# staging view, a mart, a Postgres system table).
APPROVED_TABLES = frozenset(
    f"{module.RAW_SCHEMA}.{table}"
    for module in (ingest, ingest_billing, ingest_events)
    for table in module.TABLES
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "table",
        choices=sorted(APPROVED_TABLES),
        help="schema.table to drop — must be one ingestion actually owns.",
    )
    args = parser.parse_args()

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {args.table} CASCADE"))
    print(f"Dropped {args.table} (CASCADE). Re-run the matching ingest*.py script to recreate it.")


if __name__ == "__main__":
    main()
