-- Singular test: named scenario customer 7's refund (refund_id=1) is
-- dated 2025-02-20 against an invoice booked in period 25 (Jan 2025).
-- mart_cash_movements_by_period must count that refund as cash out in
-- period 26 (Feb 2025, by refund_date) rather than period 25 (by
-- invoice_date) — the exact bug mart_revenue_reconciliation_by_period's
-- billing_refunded_amount_against_bookings deliberately does NOT fix,
-- since that column answers a different question. Fails if the refund's
-- own period doesn't show at least its amount in billing_cash_out.
with refund as (
    select
        adjustment_period_id,
        refund_amount
    from {{ ref('fct_period_close_adjustments') }}
    where refund_id = 1
)

select
    refund.adjustment_period_id,
    refund.refund_amount,
    cash_movements.billing_cash_out
from refund
inner join {{ ref('mart_cash_movements_by_period') }} as cash_movements
    on refund.adjustment_period_id = cash_movements.period_id
where cash_movements.billing_cash_out < refund.refund_amount
