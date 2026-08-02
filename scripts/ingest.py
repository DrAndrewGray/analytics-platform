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
from sqlalchemy.engine import Engine

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

TABLES = ["customers", "products", "orders", "order_items", "payments"]

RAW_SCHEMA = "raw"


def get_engine() -> Engine:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "meridian")
    user = os.getenv("POSTGRES_USER", "meridian")
    password = os.getenv("POSTGRES_PASSWORD", "meridian")
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    return create_engine(url)


def main(schema: str = RAW_SCHEMA) -> None:
    # `schema` is a parameter (not just an env var) so tests can point this
    # at an isolated schema like `raw_test`, rather than running destructive
    # operations (this function truncates and can alter tables) against the
    # same `raw` schema dbt builds its staging views from.
    engine = get_engine()
    loaded_at = datetime.now(UTC)

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

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
                    "where table_schema = :schema and table_name = :table)"
                ),
                {"schema": schema, "table": table},
            ).scalar()
            if table_exists:
                # Tolerate a table created before _loaded_at existed (e.g. a
                # persistent local volume from an earlier version of this
                # script): without this, appending a DataFrame with a column
                # the table doesn't have yet fails after the table has
                # already been truncated.
                conn.execute(
                    text(
                        f"alter table {schema}.{table} "
                        "add column if not exists _loaded_at timestamptz"
                    )
                )
                conn.execute(text(f"truncate table {schema}.{table}"))

        df.to_sql(table, engine, schema=schema, if_exists="append", index=False)
        print(f"Loaded {len(df)} rows into {schema}.{table}")


if __name__ == "__main__":
    main()
