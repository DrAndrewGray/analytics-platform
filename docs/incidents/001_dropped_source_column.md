# Incident 001: `raw.orders.channel` disappears

**Category**: required source column disappears
**Severity**: high (blocks the whole retail DAG)
**Status**: resolved (injected and recovered as a controlled demo)

## Summary

`raw.orders.channel` — the column `stg_orders.sql` renames to
`order_channel` — was dropped from the source table. `dbt build` failed
immediately at `stg_orders`, and everything downstream (10 models, 41
tests, 1 exposure) was skipped rather than built on top of a broken
staging layer. Recovery required more than the project's usual
regenerate-and-reload reset, and that gap is the actual finding worth
keeping from this incident — see "Response," below.

## Failure injected

```
uv run python scripts/inject_failure.py drop-column
```

Ran `ALTER TABLE raw.orders DROP COLUMN channel CASCADE` directly
against the shared `raw` schema. Because `raw.orders` is shared between
the `dev` and `ci` dbt targets (see docs/reliability_strategy.md), the
`CASCADE` dropped `stg_orders` and `int_order_items_enriched` in *both*
`analytics_staging`/`analytics_intermediate` (dev) and
`analytics_ci_staging`/`analytics_ci_intermediate` (ci) — one DDL
statement, both environments affected at once.

## Detection

```
$ dbt build --profiles-dir .
...
11 of 256 ERROR creating sql view model analytics_staging.stg_orders ... [ERROR in 0.14s]
...
[ERROR]: in model stg_orders (models/staging/stg_orders.sql)
  Database Error in model stg_orders (models/staging/stg_orders.sql)
  column "channel" does not exist
  LINE 17:         channel as order_channel
                   ^
...
Done. PASS=203 WARN=0 ERROR=1 SKIP=52 NO-OP=0 REUSED=0 TOTAL=256
```

One error, 52 skipped — dbt refused to build anything downstream of the
broken model rather than running on top of it.

## Impact (identified via lineage)

```
$ uv run python scripts/generate_alert_report.py
ALERT: 1 failure(s) in the most recent dbt run.

[MODEL] stg_orders — error
  message: Database Error in model stg_orders ...
  downstream models (10):
    - dim_customers
    - fct_order_items
    - fct_orders
    - int_order_items_enriched
    - int_revenue_by_period_billing
    - int_revenue_by_period_retail
    - int_volume_anomaly_by_period
    - int_volume_by_period
    - mart_revenue_reconciliation_by_period
    - mart_volume_anomalies
  downstream tests affected: 41
  downstream exposures: revenue_overview_dashboard
```

`scripts/impact_analysis.py raw.orders` gives the same 53-node closure
directly from the raw source, before ever running `dbt build` — the
same question, answered from the DAG alone. Both draw on the same
`manifest.json` `child_map`, not a hand-maintained diagram, so this list
can't drift out of sync with what dbt actually builds.

Notably, `fct_orders` appears in the impact list even though it's a
contracted model with an explicit column list — the *contract* isn't
what caught this one. `channel` was never a contracted column's source
in a way that made the contract itself fail; the break happened one
layer upstream, at `stg_orders`, before the contracted model was ever
reached. See Incident 002 for a failure the contract *does* catch
directly (a type change that flows past staging unnoticed).

## Root cause

Simulated: an upstream source system dropped a column the warehouse
depends on. In this project, "upstream" is the synthetic generator +
ingestion step; in a real pipeline, this stands in for a source team
renaming or removing a field without coordinating the change downstream.

## Response

The project's usual recovery path — regenerate synthetic data,
re-run ingestion, `dbt build` — was tried first and **failed**:

```
$ uv run python scripts/ingest.py
...
[SQL: INSERT INTO raw.orders (order_id, customer_id, order_date, status, channel, _loaded_at) VALUES ...]
(Background on this error at: https://sqlalche.me/e/20/f405)
```

`scripts/ingest.py` truncates and re-inserts into the *existing* table
by design (see its own comment: preserving the table's identity so
dependent dbt views survive a normal re-ingestion run — a real, correct
design decision for the common case). But this failure mode broke that
assumption: the table's structure itself was wrong, not just its data,
so an insert with a `channel` column against a table that no longer has
one fails outright. Truncate-and-reload only recovers from bad *data*;
it can't repair bad *structure*.

The actual fix: `DROP TABLE raw.orders`, then re-run `scripts/ingest.py`
so pandas' `to_sql` recreates the table fresh from the generator's own
schema. This is safe specifically *because* the original `CASCADE`
already removed every dbt view that depended on `raw.orders` — the
exact Postgres protection that normally blocks `DROP TABLE` (see
`scripts/ingest.py`'s own comment) had already been cleared by the
failure itself. In a real incident this wouldn't be guaranteed; see
"Follow-up," below.

```
$ psql -c "DROP TABLE raw.orders;"
$ uv run python scripts/ingest.py
Loaded 500 rows into raw.customers
Loaded 40 rows into raw.products
Loaded 3000 rows into raw.orders
Loaded 7435 rows into raw.order_items
Loaded 3000 rows into raw.payments
```

## Recovery verification

```
$ dbt build --profiles-dir .
...
Finished running 1 exposure, 2 seeds, 1 snapshot, 24 table models, 196 data tests, 32 view models
Completed successfully
Done. PASS=255 WARN=0 ERROR=0 SKIP=0 NO-OP=1 REUSED=0 TOTAL=256
```

Full dev-target rebuild, clean. `dbt build --target ci` was run
immediately after (not shown) with the same result.

## Follow-up / lessons

- **The standard recovery path has a gap it didn't have before this
  incident was written up**: it silently assumes re-ingestion targets a
  structurally-unchanged table. That assumption is usually true (data
  refreshes, not schema changes) but this incident is proof it isn't
  always. `docs/runbook.md` now calls out the `DROP TABLE` step
  explicitly for schema-shaped failures, rather than leaving it to be
  rediscovered mid-incident a second time.
- **The safety of `DROP TABLE` here was incidental**, not something the
  injector or recovery procedure actually verified in advance — it
  worked because this specific `CASCADE` happened to have already
  cleared every dependent view. A real "column disappeared" incident
  should confirm nothing else depends on the raw table before dropping
  it (`select * from pg_depend ...`), not assume it from the failure
  mode alone.
- **Both `dev` and `ci` broke from one statement.** This is a direct
  consequence of raw schemas being shared infrastructure across dbt
  targets (see docs/reliability_strategy.md) — worth knowing before
  reading too much into "this only affects one environment" for any
  raw-schema-level failure.
