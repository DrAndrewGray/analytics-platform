-- One row per accounting period: booked revenue, tax, and cash
-- collected, combined across both revenue lines (retail + billing).
-- Aggregates fct_orders / fct_invoices' own already-tested revenue
-- numbers rather than re-deriving new ones from raw tables — see
-- docs/metric_definitions_finance.md for why that distinction matters.
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
        sum(refunded_amount) as refunded_amount,
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
        coalesce(retail.booked_revenue, 0) as retail_booked_revenue,
        coalesce(retail.collected_amount, 0) as retail_collected_amount,
        coalesce(retail.tax_amount, 0) as retail_tax_amount,
        coalesce(billing.booked_revenue, 0) as billing_booked_revenue,
        coalesce(billing.collected_amount, 0) as billing_collected_amount,
        coalesce(billing.refunded_amount, 0) as billing_refunded_amount,
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
    retail_booked_revenue,
    billing_booked_revenue,
    retail_collected_amount,
    billing_collected_amount,
    billing_refunded_amount as total_refunded_amount,
    (retail_booked_revenue + billing_booked_revenue) as total_booked_revenue,
    (retail_tax_amount + billing_tax_amount) as total_tax_amount,
    (retail_collected_amount + billing_collected_amount) as total_collected_amount,
    round(
        (
            (retail_booked_revenue + billing_booked_revenue)
            - (retail_collected_amount + billing_collected_amount)
        )::numeric,
        2
    ) as variance
from combined
order by period_id
