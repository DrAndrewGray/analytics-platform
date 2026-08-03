"""Load the synthetic billing CSVs into the Postgres `raw_billing` schema.

A separate schema from `raw` (not just a separate table list): billing is
modeled as its own source system (see docs/business_context.md), and
`raw_billing.payments` is a different table from `raw.payments` — same
name, different grain, different source. Keeping them in separate schemas
makes that explicit instead of relying on everyone remembering it.
"""

from __future__ import annotations

from pathlib import Path

from scripts.ingest import get_engine, load_tables

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "billing"

TABLES = ["plans", "subscriptions", "invoices", "invoice_lines", "payments", "refunds"]

RAW_SCHEMA = "raw_billing"


def main(schema: str = RAW_SCHEMA) -> None:
    load_tables(get_engine(), schema, DATA_DIR, TABLES)


if __name__ == "__main__":
    main()
