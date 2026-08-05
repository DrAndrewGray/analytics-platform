-- Cash actually moving, by the period the money moved in — payment_date,
-- not order_date. This is deliberately a different attribution than
-- int_revenue_by_period_retail's collected_amount (which reports cash
-- collected against bookings, grouped by order_date's period): a payment
-- landing a few days after month-end belongs to a different accounting
-- period for cash purposes than the order that generated it.
--
-- Retail has only one payment row per order (see
-- docs/business_context_finance.md), so a refunded order's inflow and
-- outflow share the same known payment_date — there's no separate
-- "refund happened on this date" event the way billing has. cash_in and
-- cash_out below are both attributed to that one date; a refunded order
-- therefore contributes equally to both, netting to zero, which is the
-- most honest thing this data supports rather than picking one side.
with payments as (
    select * from {{ ref('stg_payments') }}
),

periods as (
    select * from {{ ref('accounting_periods') }}
),

joined as (
    select
        periods.period_id,
        payments.payment_id,
        payments.payment_status,
        payments.amount
    from payments
    inner join periods
        on
            payments.payment_date >= periods.period_start_date
            and payments.payment_date <= periods.period_end_date
),

aggregated as (
    select
        period_id,
        -- 'refunded' counts toward cash_in too: the single row represents
        -- a payment that succeeded and was later returned, not a payment
        -- that never happened. Omitting it here would make every refunded
        -- retail order a pure negative movement instead of netting to
        -- zero, contradicting the netting behavior described above.
        sum(case when payment_status in ('succeeded', 'refunded') then amount else 0 end)
            as cash_in,
        sum(case when payment_status = 'refunded' then amount else 0 end) as cash_out
    from joined
    group by period_id
)

select * from aggregated
