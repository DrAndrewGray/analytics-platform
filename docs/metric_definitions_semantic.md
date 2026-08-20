# Metric definitions — semantic layer

The enforced version of this catalog lives in `dbt/models/semantic/*.yml`
(`semantic_models:` and `metrics:`) — this document explains *why* each
definition looks the way it does and traces it back to the dbt model it
reuses. Every number below is produced by `mf query`, never by a
hand-written SQL aggregate in a script; see
`docs/semantic_layer_strategy.md` for why that distinction is the actual
point of this phase.

## Revenue & cash

| Metric | Formula | Source | Grain |
|---|---|---|---|
| `net_booked_revenue` | `total_net_booked_revenue` | `mart_revenue_reconciliation_by_period` | period |
| `cash_collected_against_bookings` | `total_collected_against_bookings` | same | period |
| `booking_variance` | `net_booked_revenue - cash_collected_against_bookings` | same | period |
| `cash_in` | `total_cash_in` | `mart_cash_movements_by_period` | period |
| `cash_out` | `total_cash_out` | same | period |
| `net_cash_movement` | `cash_in - cash_out` | same | period |

Two different views of the same money, on purpose — see Phase 4's own
`docs/metric_definitions_finance.md`. `net_booked_revenue`/
`cash_collected_against_bookings` answer "how much was booked/collected
against bookings made in this period"; `cash_in`/`cash_out` answer "how
much cash actually moved in this period." They're deliberately **not**
combinable in one query (see "Safe to combine," below) — that's not a
limitation, it's the same distinction Phase 4 fought to establish, now
enforced by MetricFlow instead of only by convention.

Both are tax-exclusive throughout, same as Phase 4.

## Active customers

**The one governed answer to "how many customers were active":** a
customer with at least one completed retail order booked in the period,
or at least one subscription phase overlapping the period (active on
any day within it). Engaged with both counts once, not twice.

This didn't exist as a single number anywhere in the warehouse before
this phase — Phase 2's `mart_customer_metrics.is_currently_active` is
point-in-time (as of "now") and subscription-only, not period-grained
and not combined with retail activity. A new model,
`int_active_customers_by_period.sql`, was added specifically to give
this metric one real source rather than defining it only in YAML
against nothing (see `docs/semantic_layer_strategy.md` for why that
would have been the wrong kind of shortcut).

`metric: active_customers`, source: `int_active_customers_by_period`,
grain: (period, customer).

## MRR / ARR / retention

All sourced from `mart_mrr_movements`, already reconciled in Phase 2
(`assert_mrr_bridge_reconciles.sql`) — nothing here recomputes the
bridge, only re-exposes its columns as governed metrics.

| Metric | Formula |
|---|---|
| `mrr` | `closing_mrr` |
| `arr` | `mrr * 12` |
| `opening_mrr`, `churned_mrr`, `contraction_mrr`, `expansion_mrr` | direct measures, exposed individually so the ratios below can reference them |
| `churn_rate` | `churned_mrr / opening_mrr` |
| `gross_revenue_retention` | `(opening_mrr - contraction_mrr - churned_mrr) / opening_mrr` — excludes expansion, can't exceed 100% |
| `net_revenue_retention` | `(opening_mrr - contraction_mrr - churned_mrr + expansion_mrr) / opening_mrr` — includes expansion, can exceed 100% |

`retention_rate` = `active_chain_count / cohort_size`, from
`mart_retention_cohorts`, grain: (cohort_month, months_since_cohort_start).

## Funnel & activation

`viewers`, `purchasers`, `view_to_purchase_rate` (= `purchasers /
viewers`) — from `mart_funnel_conversion`, day grain. Same-day
*presence*, not a sequential funnel: see Phase 3's own
`docs/metric_definitions_events.md` for why. A metric name alone
doesn't carry that caveat — it's why this table exists.

`signups`, `activated_customers` (customers who purchased within 14
days of signup), `activation_rate` — from `mart_activation`, customer
grain.

## A bug this phase caught: integer division in `activation_rate`

`activation_rate`'s first version (`activated_customers / signups`)
returned `0` instead of `~0.98`. Both inputs are `count_distinct`
measures, and `COUNT(DISTINCT ...)` is `bigint` in Postgres —
`bigint / bigint` truncates. The other ratio metrics here (`churn_rate`,
`retention_rate`, `view_to_purchase_rate`) didn't hit this because their
inputs are `sum()` over already-`numeric` or `bigint` mart columns, and
Postgres promotes `SUM(bigint)` to `numeric`, which divides correctly —
confirmed by checking the actual generated SQL (`mf query --explain`),
not assumed. Fixed with an explicit `::numeric` cast in the one metric
that needed it, documented inline in `_metrics.yml` rather than cast
defensively everywhere on the theory that it might matter.

## Governed dimensions

| Dimension | Owning semantic model | Available on |
|---|---|---|
| Customer (region, country, signup_date) | `sm_customers` (`dim_customers`) | `sm_orders`, `sm_invoices`, `sm_activation`, `sm_active_customers` — anything with a `customer_id` entity, via the join, not a redeclared column |
| Plan (plan_name, billing_interval) | `sm_plans` (`dim_plans`) | subscription-adjacent models with a `plan_id` entity |
| Channel (`order_channel`) | `sm_orders` (`fct_orders`) | order-level queries only — no other model has a channel concept |
| Product (category, is_active) | `sm_products` (`dim_products`) | product-adjacent models with a `product_id` entity |
| Accounting period (`is_closed`, `period_start_date`) | `sm_revenue_reconciliation` (`mart_revenue_reconciliation_by_period`) | `sm_cash_movements`, via its `period_id` foreign entity — confirmed by querying `cash_in` grouped by `period_id__is_closed` directly, not assumed from the YAML |

Verified concretely, not just declared: `mf query --metrics
active_customers --group-by customer_id__region` returns real per-region
counts (Rhode Island 20, Alaska 17, ...) even though `active_customers`
is defined on `int_active_customers_by_period`, which has no `region`
column at all — the dimension comes entirely from the join to
`sm_customers` through the shared `customer_id` entity. That's the
concrete mechanism behind "customer is governed once."

## Safe to combine

Not every metric shares a grain with every other one. Two metrics are
safely combinable in one query only if `mf list metrics` shows them
sharing a group-by dimension — don't infer this from the table above by
eye; ask MetricFlow directly, since it's checking the actual semantic
manifest, not a document that can drift from it.

| | Retail/billing period metrics | Cash-movement metrics | MRR/retention | Funnel/activation | Customer dimension |
|---|---|---|---|---|---|
| **Retail/billing period metrics** (`net_booked_revenue`, `cash_collected_against_bookings`) | ✅ same grain (`period_id`) | ⚠️ shared `period_id`, but represent different questions — combinable, not interchangeable (see above) | ❌ no shared entity | ❌ no shared entity | ❌ no `customer_id` on these two specifically |
| **Cash-movement metrics** (`cash_in`, `cash_out`) | ⚠️ see above | ✅ same grain | ❌ | ❌ | ❌ |
| **MRR/retention** (`mrr`, `churn_rate`, `retention_rate`) | ❌ | ❌ | ✅ within their own group | ❌ | ❌ no customer entity on `sm_mrr_movements`/`sm_retention_cohorts` |
| **Funnel/activation** (`viewers`, `activation_rate`) | ❌ | ❌ | ❌ | ✅ within their own group | ⚠️ `activation_rate` has a customer entity; funnel metrics don't |
| **`active_customers`** | ❌ different grain (period+customer vs. period) | ❌ | ❌ | ❌ | ✅ — this is the metric the customer dimension actually reaches |

❌ isn't a documentation claim — attempting it is a real, reproducible
error. Confirmed: `mf query --metrics mrr --group-by customer_id__region`
fails outright (`does not match any of the available group-by-items`),
because `sm_mrr_movements` has no customer entity. That failure mode is
the enforcement mechanism, not a courtesy error message — there's no way
to write a query that silently produces a wrong answer by combining
metrics that don't share a grain.

## Traceability

Every metric traces to exactly one dbt model via its `semantic_models:`
`model:` reference — `dbt docs` lineage shows the same path a
`ref('mart_revenue_reconciliation_by_period')` in a plain model would.
No metric here re-derives from a raw or staging table; see
`docs/semantic_layer_strategy.md` for why that's true by construction.
