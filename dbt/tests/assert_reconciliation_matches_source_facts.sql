-- Singular test: mart_revenue_reconciliation_by_period's total_net_booked_revenue
-- must match an independent recomputation directly from fct_orders and
-- fct_invoices, bypassing int_revenue_by_period_retail/billing entirely.
-- This catches bugs in the period-assignment or aggregation logic itself,
-- not just bugs that both the mart and its intermediates would share.
with retail_recomputed as (
    select
        periods.period_id,
        sum(orders.order_amount) as booked_revenue
    from {{ ref('fct_orders') }} as orders
    inner join {{ ref('dim_accounting_periods') }} as periods
        on
            orders.order_date >= periods.period_start_date
            and orders.order_date <= periods.period_end_date
    where orders.order_status = 'completed'
    group by periods.period_id
),

billing_recomputed as (
    select
        periods.period_id,
        sum(invoices.invoice_amount) as booked_revenue
    from {{ ref('fct_invoices') }} as invoices
    inner join {{ ref('dim_accounting_periods') }} as periods
        on
            invoices.invoice_date >= periods.period_start_date
            and invoices.invoice_date <= periods.period_end_date
    group by periods.period_id
),

recomputed as (
    select
        periods.period_id,
        coalesce(retail_recomputed.booked_revenue, 0)
        + coalesce(billing_recomputed.booked_revenue, 0) as recomputed_total_net_booked_revenue
    from {{ ref('dim_accounting_periods') }} as periods
    left join retail_recomputed on periods.period_id = retail_recomputed.period_id
    left join billing_recomputed on periods.period_id = billing_recomputed.period_id
)

select
    mart.period_id,
    mart.total_net_booked_revenue,
    recomputed.recomputed_total_net_booked_revenue
from {{ ref('mart_revenue_reconciliation_by_period') }} as mart
inner join recomputed on mart.period_id = recomputed.period_id
where
    round(mart.total_net_booked_revenue::numeric, 2)
    != round(recomputed.recomputed_total_net_booked_revenue::numeric, 2)
