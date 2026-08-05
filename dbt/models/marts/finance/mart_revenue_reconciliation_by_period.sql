-- One row per accounting period: net (tax-exclusive) booked revenue and
-- cash collected against those bookings, combined across both revenue
-- lines (retail + billing). Aggregates fct_orders / fct_invoices' own
-- already-tested revenue numbers rather than re-deriving new ones from
-- raw tables — see docs/metric_definitions_finance.md.
--
-- This is the *booking-period* view: every column here is attributed to
-- the period the underlying order/invoice was booked in, including
-- collected_against_bookings and refunded_amount_against_bookings, which
-- report cash collected/refunded *against those bookings* — not cash
-- that moved during the period itself. A payment or refund can land in
-- a later period than its invoice (see fct_period_close_adjustments for
-- a concrete case). For cash by the period it actually moved in, see
-- mart_cash_movements_by_period instead.
--
-- net_booked_revenue is tax-exclusive throughout: tax_amount is a
-- separate, illustrative pass-through line (see
-- docs/metric_definitions_finance.md), not part of recognized revenue,
-- collected cash, or variance — all three of those are consistently net
-- of tax, not gross.
with retail as (
    select
        period_id,
        sum(booked_revenue) as booked_revenue,
        sum(collected_amount) as collected_amount,
        sum(tax_amount) as tax_amount
    from {{ ref('int_revenue_by_period_retail') }}
    group by period_id
),

billing as (
    select
        period_id,
        sum(booked_revenue) as booked_revenue,
        sum(collected_amount) as collected_amount,
        sum(refunded_amount_against_bookings) as refunded_amount_against_bookings,
        sum(tax_amount) as tax_amount
    from {{ ref('int_revenue_by_period_billing') }}
    group by period_id
),

periods as (
    select * from {{ ref('dim_accounting_periods') }}
),

combined as (
    select
        periods.period_id,
        periods.period_start_date,
        periods.period_end_date,
        periods.is_closed,
        coalesce(retail.booked_revenue, 0) as retail_net_booked_revenue,
        coalesce(retail.collected_amount, 0) as retail_collected_against_bookings,
        coalesce(retail.tax_amount, 0) as retail_tax_amount,
        coalesce(billing.booked_revenue, 0) as billing_net_booked_revenue,
        coalesce(billing.collected_amount, 0) as billing_collected_against_bookings,
        coalesce(billing.refunded_amount_against_bookings, 0) as billing_refunded_amount_against_bookings,
        coalesce(billing.tax_amount, 0) as billing_tax_amount
    from periods
    left join retail on periods.period_id = retail.period_id
    left join billing on periods.period_id = billing.period_id
)

select
    period_id,
    period_start_date,
    period_end_date,
    is_closed,
    retail_net_booked_revenue,
    billing_net_booked_revenue,
    retail_collected_against_bookings,
    billing_collected_against_bookings,
    -- Billing-only: a refunded retail order is never 'completed', so it
    -- never enters retail_net_booked_revenue in the first place — there's
    -- nothing to net against. A billing invoice stays booked revenue even
    -- after a later refund, so billing needs this column and retail doesn't.
    billing_refunded_amount_against_bookings,
    (retail_net_booked_revenue + billing_net_booked_revenue) as total_net_booked_revenue,
    (retail_tax_amount + billing_tax_amount) as total_tax_amount,
    (retail_collected_against_bookings + billing_collected_against_bookings)
        as total_collected_against_bookings,
    round(
        (
            (retail_net_booked_revenue + billing_net_booked_revenue)
            - (retail_collected_against_bookings + billing_collected_against_bookings)
        )::numeric,
        2
    ) as variance
from combined
order by period_id
