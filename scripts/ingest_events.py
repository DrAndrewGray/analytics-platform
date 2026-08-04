"""Load the synthetic event CSV into the Postgres `raw_events` schema.

A third source schema, alongside `raw` (retail) and `raw_billing`
(subscriptions) — the website's event stream is yet another separate
source system in this fictional company's landscape.
"""

from __future__ import annotations

from pathlib import Path

from scripts.ingest import get_engine, load_tables

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "events"

TABLES = ["events"]

RAW_SCHEMA = "raw_events"


def main(schema: str = RAW_SCHEMA) -> None:
    load_tables(get_engine(), schema, DATA_DIR, TABLES)


if __name__ == "__main__":
    main()
