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
reconciliation, not to compute a legally correct tax bill.

`net_booked_revenue`, `collected_against_bookings`, and `variance` are
all **tax-exclusive**, consistently — `tax_amount` is tracked as a
separate, illustrative pass-through line, never added into any of the
three. Meridian doesn't actually charge or collect the tax this dataset
computes (no payment anywhere includes a tax component), so treating it
as part of "revenue" or "cash collected" would overstate both against
what the payments data actually shows.

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

## Two views of the same money: booking-period vs. cash-movement

A payment or refund doesn't necessarily land in the same accounting
period as the order/invoice that generated it — a payment made a few
days into the next month, or (concretely) customer 7's refund landing a
full month after its invoice's period. Rather than pick one attribution
and hide the other, this phase exposes both as separate marts, sharing
the same `dim_accounting_periods` grain so they're directly comparable:

**`mart_revenue_reconciliation_by_period`** — the **booking-period**
view. Every column is attributed to the period the underlying order or
invoice was *booked* in, including how much of that booking has since
been collected or refunded, however later that happened:

- `retail_net_booked_revenue` — sum of `fct_orders.order_amount` for
  completed orders in the period (Phase 1's own recognized-value number).
- `billing_net_booked_revenue` — sum of `fct_invoices.invoice_amount` in
  the period (Phase 2's own recognized-value number).
- `total_net_booked_revenue` = the two combined.
- `total_tax_amount` — computed per the tax section above, on both lines.
- `retail_collected_against_bookings` / `billing_collected_against_bookings`
  / `total_collected_against_bookings` — cash collected *against the
  bookings made in this period*, regardless of which period the payment
  itself landed in.
- `billing_refunded_amount_against_bookings` — refunds against invoices
  booked in this period, regardless of which period the refund itself
  landed in. Billing-only: a refunded retail order is never
  `order_status = 'completed'`, so it never enters
  `retail_net_booked_revenue` to begin with — there's nothing to net
  against for retail here.
- `variance` = `total_net_booked_revenue - total_collected_against_bookings`,
  the same recognized-vs-cash gap each domain already tracks
  individually, now at the whole-company level.

**`mart_cash_movements_by_period`** — the **cash-movement** view. Every
column is attributed to the period the cash itself actually moved:
`payment_date` for inflows, `refund_date` for outflows.

- `retail_cash_in` / `billing_cash_in` — successful payments, by
  `payment_date`.
- `retail_cash_out` / `billing_cash_out` — refunds, by `refund_date`
  (billing) or `payment_date` (retail — see below).
- `retail_net_cash_movement` / `billing_net_cash_movement` /
  `total_net_cash_movement` — inflows minus outflows.

Retail has only one payment row per order and no distinct refund-date
column (see "A real, honest scope limit" in
`docs/business_context_finance.md`), so a refunded retail order's
inflow and outflow are both attributed to its single known
`payment_date` — they net to zero for that order, which is the most
honest statement this data supports, rather than inventing a
later date it doesn't have.

Neither mart recomputes revenue from raw tables — both aggregate the
existing `fct_orders` / `fct_invoices` / `stg_payments` /
`stg_billing__payments` / `stg_billing__refunds` models, which already
carry each domain's own tested logic. Reconciling *those* numbers, not
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
