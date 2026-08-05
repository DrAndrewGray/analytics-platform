# Business context: finance & revenue reconciliation

Phase 4 doesn't add a new source system — it adds an accounting layer on
top of the two that already exist (Phase 1 retail, Phase 2 Meridian+
billing), plus two small pieces of reference data: **tax rates** and
**accounting periods**. The questions this phase answers are company-wide
questions finance would actually ask, not per-domain ones:

- Why does booked revenue differ from cash received, across *both*
  revenue lines combined?
- What changed after a reporting period was already closed?
- Can a number on a finance report be traced back to the raw rows that
  produced it?

## Why seeds, not a new source system

`tax_rates` and `accounting_periods` are reference data, not
transactional extracts from some external system — there's no
"raw_finance" source producing a stream of rows the way orders or events
are produced. dbt's `seed` mechanism (`dbt/seeds/*.csv`, loaded via
`dbt seed`) is the correct tool for exactly this: small, human-maintained
tables that change rarely and are checked into version control directly,
not ingested through the Python/Postgres pipeline the transactional
domains use.

## Accounting periods

Monthly periods from 2023-01 (matching `dim_date`'s start) through the
current month. Each period has a `closed_at` timestamp — 10 days after
month-end, standard month-close cadence — except the two most recent
periods, which stay open (`closed_at` is null) to represent the current
and still-closing month. A period being "closed" is what makes a
later-arriving refund or adjustment against it a *restatement* rather
than just a normal part of that period's numbers.

## Tax

Applied as a flat rate per customer `region`, from `dbt/seeds/tax_rates.csv`
(approximate 2020s-era US state sales tax rates — illustrative, not
authoritative; see `docs/metric_definitions_finance.md` for why this is
a deliberately simple model, not a real tax engine).

## A real, honest scope limit: retail has no distinct adjustment date

Billing's `refunds.refund_date` is a genuine, separate timestamp from
the original `invoice_date` — a real adjustment event. Retail's Phase 1
schema doesn't have that: a refunded order has one payment row with
`status = 'refunded'` and a single `payment_date`, with no distinct
"when was this refunded" timestamp. That's a realistic limitation of a
simpler source system, not a bug to paper over by inventing a date that
isn't really there. Late-adjustment-after-close analysis
(`int_period_close_adjustments`, `fct_period_close_adjustments`) is
therefore scoped to billing only; retail still gets period-level revenue
reconciliation (booked vs. collected by month), just not the
adjustment-timing drill-down. See
`docs/metric_definitions_finance.md`.

## Two questions that look alike but aren't: booked vs. moved

"How much revenue did we book in March" and "how much cash moved through
the business in March" are different questions whenever a payment or
refund crosses a month boundary from the order/invoice that generated
it — which happens routinely (44 billing invoice/payment pairs in this
dataset alone land in different months). Collapsing them into one
column, as the first version of this phase did, silently answers one
question while labeling the result as if it were the other. Both
questions are legitimate and answerable from this data, so both get
their own mart: `mart_revenue_reconciliation_by_period` (booking-period)
and `mart_cash_movements_by_period` (cash-movement). See
`docs/metric_definitions_finance.md` for the exact column-level split.
