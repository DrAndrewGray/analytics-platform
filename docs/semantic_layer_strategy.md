# Semantic layer strategy — Phase 6

Phases 1–5 built a warehouse that's correct, reconciled, and monitored.
This phase asks a different question again: once the numbers are right,
how do you stop two different reports from disagreeing about what
"revenue" or "active customer" means? Two dashboards built independently
against the same warehouse can each write their own `sum(order_amount)`
and quietly diverge the moment one of them adds a filter the other
doesn't — not because either query is wrong, but because "revenue" was
never defined once, in one place, for everyone to share.

## What this phase is, and isn't

This is a **governance layer on top of the existing warehouse**, not a
new revenue domain and not new ingestion. Every metric here is defined
against a model Phases 1–5 already built and tested — nothing is
re-derived from raw tables a second time, for the same reason Phase 4's
reconciliation marts aggregate `fct_orders`/`fct_invoices` instead of
recomputing from source: reusing an already-tested number is what makes
governance real instead of aspirational.

Explicitly out of scope, per the brief: no new ingestion infrastructure,
no orchestration, no AI. The two BI outputs are generated, checked-in
files (`docs/bi/*.html`), not a hosted dashboard tool — same reasoning
Phase 5 used for its own "dashboard" (`docs/reliability_strategy.md`):
the deliverable is proving governance works, not standing up BI
infrastructure.

## Why dbt's own Semantic Layer (MetricFlow), not a hand-rolled one

dbt has shipped a real semantic-layer primitive since 1.6 —
`semantic_models:` and `metrics:` YAML, validated by `dbt parse` /
`mf validate-configs`, queryable locally via the `mf` CLI
(`dbt-metricflow` package) against the same Postgres connection
`profiles.yml` already defines. No dbt Cloud account needed, no new
warehouse, no new service to run — confirmed by installing it and
running a real query against this project's own data before committing
to the approach (see the commit history for the exact feasibility
check). Given the project is already dbt-native, this is the
narrower, more credible claim than building a second, parallel
"metrics" concept from scratch: it demonstrates a specific, real,
in-demand dbt feature rather than reinventing a smaller version of it.

**The concrete mechanism that satisfies "two consumers can't
independently redefine revenue":** a metric is defined exactly once, in
`dbt/models/semantic/*.yml`. Both BI outputs (`scripts/generate_*.py`)
query it through `mf query`, never through a hand-written SQL
aggregate — there is no code path in this repo where a script can type
`sum(order_amount)` for "revenue" instead of asking MetricFlow for the
`net_booked_revenue` metric. `scripts/verify_semantic_layer.py` is the
proof: it independently recomputes each metric directly from its source
mart and asserts the two agree, the same "recompute independently, then
assert equality" pattern Phase 4/5's own tests already use.

## Why semantic models sit on marts, not raw tables

Every `semantic_models:` entry below has `model: ref('fct_orders')` (or
another mart), never a staging or raw reference. The alternative —
defining measures against `stg_orders` or `raw.orders` directly — would
mean the semantic layer re-implements grain, filtering, and revenue
recognition logic marts already carry (e.g. `fct_orders.order_amount`
excludes nothing; the "completed only" filter that makes it *booked
revenue* lives in `int_revenue_by_period_retail`). Building on marts
keeps the semantic layer thin by construction: it can't drift from the
marts' own tested logic because it has no logic of its own to drift.

## Governed dimensions

Customer, plan, channel, product, and accounting period are each
defined as a semantic-model **dimension** exactly once
(`docs/metric_definitions_semantic.md` has the full catalog), sourced
from the same `dim_*`/mart columns every existing mart already uses.
MetricFlow enforces this at query time in a way a hand-rolled layer
can't cheaply replicate: `mf query` rejects a `--group-by` dimension
that isn't declared on the metric's semantic model, so "can this metric
be sliced by region" isn't a convention someone has to remember — it's
a validation error if violated.

## The "safe to combine" question

Not every metric shares a grain with every other metric. `revenue` is
period-grained and can be sliced by channel or region; `mrr` is
month-grained and has no channel dimension at all (a subscription isn't
sold through a checkout channel); `retention_rate` is cohort-grained and
combining it with period-grained revenue in one query would silently
average across an incompatible dimension. `docs/metric_definitions_semantic.md`
documents this explicitly as a matrix, and it's independently verifiable
run `mf list metrics` yourself: it lists each metric's actual available
dimensions, straight from the semantic manifest — not from someone's
memory of what should be true.

## Reconciliation testing

`scripts/verify_semantic_layer.py` runs `mf query` for every core metric
at the same grain its source mart already provides, and compares the
result row-for-row against a direct SQL query of that mart — the same
"recompute independently" testing discipline used throughout this
project (see Phase 4's `assert_reconciliation_matches_source_facts.sql`,
Phase 5's `assert_cash_movements_match_source_facts.sql`). A mismatch
here would mean MetricFlow's generated SQL diverged from the
straightforward mart aggregate for some reason — exactly the class of
silent bug a governed semantic layer exists to make impossible to miss.
