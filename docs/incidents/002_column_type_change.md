# Incident 002: `raw.orders.customer_id` silently changes type

**Category**: a source column changes type
**Severity**: high (breaks a contracted mart + a referential-integrity test)
**Status**: resolved (injected and recovered as a controlled demo)

## Summary

`raw.orders.customer_id` changed from `bigint` to `text`. Unlike
Incident 001, this failure doesn't stop the DAG at the first broken
model — `stg_orders` doesn't cast `customer_id`, so it *recreates
successfully* with the wrong type and quietly passes the bad type one
layer downstream. Two independent controls caught it anyway, by two
different mechanisms: a `relationships` test failed with a raw Postgres
type-mismatch error, and `fct_orders`'s **enforced dbt contract**
refused to materialize the table at all. This is the incident that
actually exercises what `docs/data_contracts.md` argues contracts are
for — Incident 001's failure never reached a contracted model.

## Failure injected

```
uv run python scripts/inject_failure.py change-column-type
```

Postgres won't `ALTER COLUMN ... TYPE` a column a view depends on (no
`CASCADE` option exists for that operation), so the injector first drops
`stg_orders` in both `analytics_staging` and `analytics_ci_staging`
(`DROP VIEW IF EXISTS ... CASCADE`), then runs
`ALTER TABLE raw.orders ALTER COLUMN customer_id TYPE text`.

## Detection

```
$ dbt build --profiles-dir .
...
[ERROR]: in test relationships_stg_orders_customer_id__customer_id__ref_stg_customers_
  Database Error in test relationships_stg_orders_customer_id...
  operator does not exist: text = bigint
  LINE 31:     on child.from_field = parent.to_field
                                   ^
  HINT:  No operator matches the given name and argument types. You might need to add explicit type casts.

[ERROR]: in model fct_orders (models/marts/core/fct_orders.sql)
  Compilation Error in model fct_orders (models/marts/core/fct_orders.sql)
  This model has an enforced contract that failed.
  Please ensure the name, data_type, and number of columns in your contract match the columns in your model's definition.

  | column_name | definition_type | contract_type | mismatch_reason    |
  | ----------- | --------------- | ------------- | ------------------ |
  | customer_id | TEXT            | LONGINTEGER   | data type mismatch |

Done. PASS=217 WARN=0 ERROR=2 SKIP=37 NO-OP=0 REUSED=0 TOTAL=256
```

`stg_orders` itself built with **no error at all** — worth sitting with,
since it's the actual point of this incident. `select ... customer_id
... from source` doesn't care what type `customer_id` is; the view
recreates, and the wrong type flows silently into
`analytics_staging.stg_orders.customer_id` (now `text`). Nothing failed
until something *downstream* either compared it against a real `bigint`
(the `relationships` test) or declared what type it was supposed to be
in writing (`fct_orders`'s contract).

## Impact (identified via lineage)

```
$ uv run python scripts/generate_alert_report.py
ALERT: 2 failure(s) in the most recent dbt run.

[TEST] relationships_stg_orders_customer_id__customer_id__ref_stg_customers_ — error
  downstream models (4): dim_customers, int_revenue_by_period_billing,
    int_revenue_by_period_retail, mart_revenue_reconciliation_by_period
  downstream tests affected: 21
  downstream exposures: revenue_overview_dashboard

[MODEL] fct_orders — error
  downstream models (5): int_revenue_by_period_retail,
    int_volume_anomaly_by_period, int_volume_by_period,
    mart_revenue_reconciliation_by_period, mart_volume_anomalies
  downstream tests affected: 23
  downstream exposures: revenue_overview_dashboard
```

Two separate blast radii from one root cause, because the two controls
caught it at two different points in the DAG (the `relationships` test
on `stg_orders` directly; the contract two models further down at
`fct_orders`) — a concrete illustration of defense in depth actually
doing something, not just existing on paper.

## Root cause

Simulated: an upstream source system changed a column's type without
announcing it — the same category of change a schema migration, a
different extraction tool, or a vendor API version bump could cause in
a real pipeline.

## Response

Recovery needed the table dropped and reloaded fresh, same as Incident
001 — but with an extra wrinkle worth recording. The first attempt used
a plain `DROP TABLE raw.orders`:

```
$ psql -c "DROP TABLE raw.orders;"
ERROR:  cannot drop table raw.orders because other objects depend on it
DETAIL:  view analytics_staging.stg_orders depends on table raw.orders
```

This *shouldn't* have been blocked — the injector had already dropped
`stg_orders` before the `ALTER`. What happened in between: running
`dbt build` to observe the failure (the "Detection" step, above)
**recreated `stg_orders`** as a side effect, since it builds
successfully on its own (see "Detection"). By the time recovery started,
the view was back, now pointing at the wrong-typed column. The fix was
`DROP TABLE raw.orders CASCADE` instead of a plain `DROP TABLE`:

```
$ psql -c "DROP TABLE raw.orders CASCADE;"
NOTICE:  drop cascades to view analytics_staging.stg_orders
NOTICE:  drop cascades to view analytics_intermediate.int_order_items_enriched
DROP TABLE
$ uv run python scripts/ingest.py
Loaded 500 rows into raw.customers
Loaded 3000 rows into raw.orders
...
```

## Recovery verification

```
$ dbt build --profiles-dir .
Finished running 1 exposure, 2 seeds, 1 snapshot, 24 table models, 196 data tests, 32 view models
Completed successfully
Done. PASS=255 WARN=0 ERROR=0 SKIP=0 NO-OP=1 REUSED=0 TOTAL=256
```

## Follow-up / lessons

- **Running `dbt build` to *diagnose* a schema-shaped failure can
  change what's needed to *recover* from it.** The natural instinct —
  build once to see the error, fix it, build again — doesn't hold here,
  because the diagnostic build itself partially repairs the DAG (any
  view that doesn't happen to reference the broken column or type
  rebuilds fine) while leaving the actual root cause (the raw table)
  broken. `docs/runbook.md` now says to go straight to `DROP TABLE ...
  CASCADE` for schema-shaped failures rather than a plain `DROP TABLE`,
  specifically because of this.
- **Contracts and generic tests catch different failures at different
  depths, and both matter.** The `relationships` test caught this one
  step downstream, at `stg_orders` itself, because the comparison it
  runs (`child.from_field = parent.to_field`) forced a type check
  Postgres couldn't silently skip. The contract caught it two more
  models downstream, at the boundary this project actually cares about
  protecting. Neither would have caught Incident 001's failure (a
  missing column, not a type mismatch) — that one was a plain
  compilation error, one layer earlier than either control gets a
  chance to run.
