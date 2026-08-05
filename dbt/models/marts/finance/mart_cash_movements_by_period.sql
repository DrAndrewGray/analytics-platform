-- One row per accounting period: cash that actually moved in that
-- period, by payment_date/refund_date — not cash collected against
-- bookings made in that period (that's mart_revenue_reconciliation_by_period).
-- The two views disagree whenever a payment or refund crosses a period
-- boundary from the invoice/order that generated it; both are legitimate
-- questions, so both are exposed rather than picking one.
with retail as (
    select * from {{ ref('int_cash_movements_retail') }}
),

billing as (
    select * from {{ ref('int_cash_movements_billing') }}
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
        coalesce(retail.cash_in, 0) as retail_cash_in,
        coalesce(retail.cash_out, 0) as retail_cash_out,
        coalesce(billing.cash_in, 0) as billing_cash_in,
        coalesce(billing.cash_out, 0) as billing_cash_out
    from periods
    left join retail on periods.period_id = retail.period_id
    left join billing on periods.period_id = billing.period_id
)

select
    period_id,
    period_start_date,
    period_end_date,
    is_closed,
    retail_cash_in,
    retail_cash_out,
    billing_cash_in,
    billing_cash_out,
    (retail_cash_in - retail_cash_out) as retail_net_cash_movement,
    (billing_cash_in - billing_cash_out) as billing_net_cash_movement,
    (retail_cash_in + billing_cash_in) as total_cash_in,
    (retail_cash_out + billing_cash_out) as total_cash_out,
    (
        (retail_cash_in + billing_cash_in) - (retail_cash_out + billing_cash_out)
    ) as total_net_cash_movement
from combined
order by period_id
