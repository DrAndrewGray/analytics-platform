"""Load the synthetic CSVs into the Postgres `raw` schema.

Stands in for a real ingestion step (e.g. an API extractor). Deliberately
simple: truncate-and-reload per table, since the synthetic generator is the
system of record here. A real ingestion framework (incremental extraction,
retries, idempotency) is a separate, later portfolio project.

`load_tables()` is the reusable core — `scripts/ingest_billing.py` calls it
too, pointed at a different schema and table list, rather than duplicating
this loop for a second source system.
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


def _coerce_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Parse text columns that are unambiguously ISO dates into real dates.

    pandas.read_csv() doesn't parse dates by default, and to_sql() then
    infers each column's SQL type from whatever dtype it ended up with —
    silently landing every date column as TEXT. Comparisons, min(), and
    max() happen to still work on ISO-format text (it sorts identically to
    the real date), which is exactly why this went unnoticed until a model
    needed date_trunc(), which text doesn't support at all.

    Deliberately conservative: a column is only converted if every
    non-null value matches %Y-%m-%d, so this can't misfire on an
    unrelated text column.
    """
    for column in df.columns:
        # Not `dtype == "object"`: pandas 3.x's read_csv returns a
        # dedicated StringDtype for text columns, not the classic
        # `object` dtype, so that check silently matched nothing.
        if not pd.api.types.is_string_dtype(df[column]):
            continue
        parsed = pd.to_datetime(df[column], format="%Y-%m-%d", errors="coerce")
        is_unambiguous_date_column = (parsed.notna() | df[column].isna()).all()
        if is_unambiguous_date_column:
            df[column] = parsed.dt.date
    return df


def load_tables(engine: Engine, schema: str, data_dir: Path, tables: list[str]) -> None:
    loaded_at = datetime.now(UTC)

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

    for table in tables:
        csv_path = data_dir / f"{table}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"{csv_path} not found — run the matching generator first")
        df = _coerce_date_columns(pd.read_csv(csv_path))
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


def main(schema: str = RAW_SCHEMA) -> None:
    # `schema` is a parameter (not just an env var) so tests can point this
    # at an isolated schema like `raw_test`, rather than running destructive
    # operations (this function truncates and can alter tables) against the
    # same `raw` schema dbt builds its staging views from.
    load_tables(get_engine(), schema, DATA_DIR, TABLES)


if __name__ == "__main__":
    main()
