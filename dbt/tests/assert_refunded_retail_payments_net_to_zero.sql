-- Singular test: a refunded retail payment has only one known date
-- (payment_date), so int_cash_movements_retail.sql counts it toward
-- both cash_in (the payment succeeded before it was refunded) and
-- cash_out (the refund itself) on that same date. Per period, the
-- refunded-payment total must therefore be present in both
-- retail_cash_in and retail_cash_out — not just cash_out — or a
-- refunded order becomes a pure negative movement instead of netting to
-- zero. Directly regression-guards the bug where cash_in only counted
-- 'succeeded' and silently dropped every refunded payment's inflow.
with refunded_by_period as (
    select
        periods.period_id,
        sum(payments.amount) as refunded_amount
    from {{ ref('stg_payments') }} as payments
    inner join {{ ref('accounting_periods') }} as periods
        on
            payments.payment_date >= periods.period_start_date
            and payments.payment_date <= periods.period_end_date
    where payments.payment_status = 'refunded'
    group by periods.period_id
)

select
    refunded_by_period.period_id,
    refunded_by_period.refunded_amount,
    cash_movements.retail_cash_in,
    cash_movements.retail_cash_out
from refunded_by_period
inner join {{ ref('mart_cash_movements_by_period') }} as cash_movements
    on refunded_by_period.period_id = cash_movements.period_id
where
    round(cash_movements.retail_cash_in::numeric, 2) < round(refunded_by_period.refunded_amount::numeric, 2)
    or round(cash_movements.retail_cash_out::numeric, 2) != round(refunded_by_period.refunded_amount::numeric, 2)
