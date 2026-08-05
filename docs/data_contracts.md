# Data contracts

## What a dbt model contract actually adds over a test

A generic `not_null`/`unique` test runs *after* a model is built: dbt
creates the table (or view), then runs a `select` against it that fails
if the invariant doesn't hold. The bad data was queryable, however
briefly, before the test caught it. A dbt **contract**
(`config: {contract: {enforced: true}}` plus an explicit column list
with `data_type`s, and optionally `constraints`) is enforced *at build
time*: dbt generates the `create table`/`create view` DDL from the
declared column list and types, and Postgres rejects the build outright
if the query's actual output doesn't match — wrong column, wrong type,
or (with a `primary_key` constraint) a duplicate grain value never gets
written to the table in the first place. That's a materially different
failure mode: a contract violation means the bad table never exists;
a test violation means it existed and got caught. Both matter — this
phase uses both deliberately, not one instead of the other.

## Which models are contracted, and why

Contracts add real friction (every column must be declared, up front,
with an exact type — see "Recovery cost" below), so this phase applies
them narrowly to the models where a silent shape change would be
worst: the finance-facing marts a reconciliation report would actually
be read from.

| Model | Grain | Primary key constraint | Why contracted |
|---|---|---|---|
| `fct_orders` | one row per order | `order_id` | Feeds `int_revenue_by_period_retail` and both finance marts; a duplicate `order_id` here would double-count revenue everywhere downstream. |
| `fct_invoices` | one row per invoice | `invoice_id` | Same reasoning, billing side. |
| `mart_revenue_reconciliation_by_period` | one row per accounting period | `period_id` | The actual booking-period reconciliation report — a shape change here is the scenario this whole phase exists to catch. |
| `mart_cash_movements_by_period` | one row per accounting period | `period_id` | The actual cash-movement report — same reasoning. |

Everything upstream of these (staging, intermediate models,
non-finance marts) is left uncontracted deliberately. Contracting every
model in the DAG would mean every routine column rename anywhere in the
warehouse requires updating a contract, which trades a small amount of
extra safety for a large amount of ongoing friction on models that
aren't the ones actually being reconciled against. Four models, chosen
because they're the ones a stakeholder would actually screenshot.

## Why source contracts don't exist the same way — and what stands in for one

dbt's contract primitive is model-level: it constrains what a `select`
*produces*, not what a raw source table looks like before dbt ever
touches it. There's no dbt-native way to say "fail the build if
`raw.orders` loses a column" — by the time a model tries to `select` a
column that's gone, you get a Postgres compilation error, which *is* a
failure signal, but a late, unstructured one buried in a stack trace
rather than a named, actionable check.

`scripts/check_source_schema.py` fills that gap: it queries
`information_schema.columns` for every table across all three raw
schemas, compares the result against a checked-in JSON snapshot
(`docs/expected_source_schemas.json`), and reports exactly which
columns are missing, added, or changed type — before `dbt build` ever
runs, not after it fails partway through. This is the practical
equivalent of a source contract, built from a plain SQL catalog query
because dbt doesn't offer one, not because a checked-in snapshot is
somehow the ideal design. Regenerating the snapshot
(`--update` flag) is a deliberate, reviewable action — a real source
schema change should show up as a diff in a pull request, the same way
a `.yml` contract change would.

## Recovery cost — the real tradeoff of enforcing a contract

Enforcing a contract on `fct_orders` means every column produced by
that model's `select` must appear, in the same order... no — dbt
contracts match by *name*, not position, but every declared column must
be present with the exact declared type, and no undeclared column may
appear. Practically: adding a new column to `fct_orders` now means two
edits instead of one — the model's SQL, and the contract's column list
in `_core__models.yml` — or the build fails with a clear "this
model's signature has changed" error rather than silently shipping the
new column. That's the point: a contracted mart's shape is supposed to
require a deliberate, reviewable change, not an incidental one.
