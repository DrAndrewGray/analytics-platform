-- Cash actually moving, by the period the money moved — payment_date for
-- inflows, refund_date for outflows — not by invoice_date. Deliberately
-- separate from int_revenue_by_period_billing's collected_amount/
-- refunded_amount, which report cash against the invoice's own booking
-- period. Billing has genuinely separate payment_date and refund_date
-- columns (unlike retail), so inflows and outflows can be attributed to
-- the period they actually happened in, including a refund landing in a
-- later period than its original invoice/payment.
with payments as (
    select * from {{ ref('stg_billing__payments') }}
),

refunds as (
    select * from {{ ref('stg_billing__refunds') }}
),

periods as (
    select * from {{ ref('accounting_periods') }}
),

payments_by_period as (
    select
        periods.period_id,
        sum(case when payments.payment_status = 'succeeded' then payments.payment_amount else 0 end)
            as cash_in
    from payments
    inner join periods
        on
            payments.payment_date >= periods.period_start_date
            and payments.payment_date <= periods.period_end_date
    group by periods.period_id
),

refunds_by_period as (
    select
        periods.period_id,
        sum(refunds.refund_amount) as cash_out
    from refunds
    inner join periods
        on
            refunds.refund_date >= periods.period_start_date
            and refunds.refund_date <= periods.period_end_date
    group by periods.period_id
),

-- Full outer join, not a join to periods: a period can have refunds with
-- no payments (or vice versa) since the two are grouped independently
-- above. The downstream mart is what fills in periods with neither.
combined as (
    select
        coalesce(payments_by_period.period_id, refunds_by_period.period_id) as period_id,
        coalesce(payments_by_period.cash_in, 0) as cash_in,
        coalesce(refunds_by_period.cash_out, 0) as cash_out
    from payments_by_period
    full outer join refunds_by_period on payments_by_period.period_id = refunds_by_period.period_id
)

select * from combined
