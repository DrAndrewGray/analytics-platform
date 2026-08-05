-- Singular test: mart_cash_movements_by_period's total_cash_in/total_cash_out
-- must match an independent recomputation directly from stg_payments,
-- stg_billing__payments, and stg_billing__refunds, bypassing
-- int_cash_movements_retail/billing entirely. Catches a bug in the
-- payment-date/refund-date period-assignment logic itself, not just one
-- shared between the mart and its own intermediates.
with retail_in_recomputed as (
    select
        periods.period_id,
        sum(payments.amount) as cash_in
    from {{ ref('stg_payments') }} as payments
    inner join {{ ref('dim_accounting_periods') }} as periods
        on
            payments.payment_date >= periods.period_start_date
            and payments.payment_date <= periods.period_end_date
    where payments.payment_status = 'succeeded'
    group by periods.period_id
),

retail_out_recomputed as (
    select
        periods.period_id,
        sum(payments.amount) as cash_out
    from {{ ref('stg_payments') }} as payments
    inner join {{ ref('dim_accounting_periods') }} as periods
        on
            payments.payment_date >= periods.period_start_date
            and payments.payment_date <= periods.period_end_date
    where payments.payment_status = 'refunded'
    group by periods.period_id
),

billing_in_recomputed as (
    select
        periods.period_id,
        sum(payments.payment_amount) as cash_in
    from {{ ref('stg_billing__payments') }} as payments
    inner join {{ ref('dim_accounting_periods') }} as periods
        on
            payments.payment_date >= periods.period_start_date
            and payments.payment_date <= periods.period_end_date
    where payments.payment_status = 'succeeded'
    group by periods.period_id
),

billing_out_recomputed as (
    select
        periods.period_id,
        sum(refunds.refund_amount) as cash_out
    from {{ ref('stg_billing__refunds') }} as refunds
    inner join {{ ref('dim_accounting_periods') }} as periods
        on
            refunds.refund_date >= periods.period_start_date
            and refunds.refund_date <= periods.period_end_date
    group by periods.period_id
),

recomputed as (
    select
        periods.period_id,
        coalesce(retail_in_recomputed.cash_in, 0)
        + coalesce(billing_in_recomputed.cash_in, 0) as recomputed_total_cash_in,
        coalesce(retail_out_recomputed.cash_out, 0)
        + coalesce(billing_out_recomputed.cash_out, 0) as recomputed_total_cash_out
    from {{ ref('dim_accounting_periods') }} as periods
    left join retail_in_recomputed on periods.period_id = retail_in_recomputed.period_id
    left join retail_out_recomputed on periods.period_id = retail_out_recomputed.period_id
    left join billing_in_recomputed on periods.period_id = billing_in_recomputed.period_id
    left join billing_out_recomputed on periods.period_id = billing_out_recomputed.period_id
)

select
    mart.period_id,
    mart.total_cash_in,
    recomputed.recomputed_total_cash_in,
    mart.total_cash_out,
    recomputed.recomputed_total_cash_out
from {{ ref('mart_cash_movements_by_period') }} as mart
inner join recomputed on mart.period_id = recomputed.period_id
where
    round(mart.total_cash_in::numeric, 2) != round(recomputed.recomputed_total_cash_in::numeric, 2)
    or round(mart.total_cash_out::numeric, 2) != round(recomputed.recomputed_total_cash_out::numeric, 2)
