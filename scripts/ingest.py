"""Load the synthetic CSVs into the Postgres `raw` schema.

Stands in for a real ingestion step (e.g. an API extractor). Deliberately
simple: truncate-and-reload per table, since the synthetic generator is the
system of record here. A real ingestion framework (incremental extraction,
retries, idempotency) is a separate, later portfolio project.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

TABLES = ["customers", "products", "orders", "order_items", "payments"]


def get_engine():
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "meridian")
    user = os.getenv("POSTGRES_USER", "meridian")
    password = os.getenv("POSTGRES_PASSWORD", "meridian")
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    return create_engine(url)


def main() -> None:
    engine = get_engine()
    loaded_at = datetime.now(UTC)

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))

    for table in TABLES:
        csv_path = DATA_DIR / f"{table}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(
                f"{csv_path} not found — run scripts/generate_synthetic_data.py first"
            )
        df = pd.read_csv(csv_path)
        # A genuine ingestion-time timestamp, distinct from business dates
        # like order_date/signup_date. Source freshness should measure how
        # long ago a row actually arrived through the pipeline, not what
        # date the row's business data happens to reference.
        df["_loaded_at"] = loaded_at

        # Truncate (not drop-and-recreate): dbt staging views reference these
        # tables directly, and Postgres refuses to drop a table that a view
        # depends on. Truncating preserves the table's identity so those
        # views stay valid across re-ingestion runs.
        with engine.begin() as conn:
            table_exists = conn.execute(
                text(
                    "select exists (select 1 from information_schema.tables "
                    "where table_schema = 'raw' and table_name = :table)"
                ),
                {"table": table},
            ).scalar()
            if table_exists:
                conn.execute(text(f"truncate table raw.{table}"))

        df.to_sql(table, engine, schema="raw", if_exists="append", index=False)
        print(f"Loaded {len(df)} rows into raw.{table}")


if __name__ == "__main__":
    main()
