# Metric definitions and modeling decisions — finance & revenue reconciliation

## Period assignment

A transaction belongs to the accounting period whose
`[period_start_date, period_end_date]` range contains its own date:
`order_date` for retail orders, `invoice_date` for billing invoices.
This is the period its revenue is *booked* in, regardless of when cash
was actually collected.

## Tax

`tax_amount = revenue * tax_rate`, where `tax_rate` comes from the
customer's `region` (`dbt/seeds/tax_rates.csv`). This is a flat,
illustrative rate, not a real tax engine — deliberately: real sales tax
depends on product taxability, nexus rules, local (not just state)
jurisdiction, and exemptions, none of which this dataset models. The
point of including tax here is to show *where* a tax line belongs in a
reconciliation (`booked_revenue = net_revenue + tax_amount`), not to
compute a legally correct tax bill. `net_of_tax_revenue` is what's
actually being reconciled against cash collected elsewhere in this
project, since Meridian doesn't keep tax it collects on behalf of a
jurisdiction.

## Period-close adjustments (billing only — see business context doc)

A billing refund is a **late adjustment** if:

1. Its invoice's accounting period (by `invoice_date`) has a non-null
   `closed_at`, and
2. The refund's `refund_date` is after that period's `closed_at`.

In other words: the period was already closed by the time the refund
happened. The adjustment itself gets assigned to *its own* period (by
`refund_date`) for reporting — it lands in whichever period is open when
the money actually moves — while `fct_period_close_adjustments` keeps
the link back to the original period so both can be reconciled.

A refund against a still-open period, or one processed before its
period's `closed_at`, is not a "late" adjustment — it's just normal
in-period activity and doesn't need special handling.

## Revenue reconciliation, by period

`mart_revenue_reconciliation_by_period` combines both revenue lines:

- `retail_booked_revenue` — sum of `fct_orders.order_amount` for
  completed orders in the period (Phase 1's own recognized-value number).
- `billing_booked_revenue` — sum of `fct_invoices.invoice_amount` in the
  period (Phase 2's own recognized-value number).
- `total_booked_revenue` = the two combined.
- `total_tax` — computed per the tax section above, on both lines.
- `total_collected` — net cash actually collected across both domains
  (`fct_orders.amount_collected` + `fct_invoices.net_collected_amount`).
- `total_refunded` — from both domains.
- `variance` = `total_booked_revenue - total_collected`, the same
  recognized-vs-cash gap each domain already tracks individually, now at
  the whole-company level.

This mart doesn't recompute revenue from raw tables — it aggregates the
existing `fct_orders` / `fct_invoices` marts, which already carry each
domain's own tested revenue logic. Reconciling *those* numbers, not
re-deriving new ones, is what makes this a genuine reconciliation rather
than a second, possibly-divergent revenue calculation.

## Traceability

A worked example — tracing one specific number in
`mart_revenue_reconciliation_by_period` back through
`fct_invoices` → `int_invoice_payment_status` → `stg_billing__invoices`
→ raw rows — is in the README's Phase 4 section, not a separate mart:
traceability is a property of the DAG (every mart here is `ref()`-built
on tested upstream models, so `dbt docs` lineage already shows the path)
rather than something that needs its own table.
