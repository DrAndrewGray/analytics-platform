-- Singular test: named scenario customer 7's refund (refund_id=1) is
-- dated 2025-02-20 against an invoice booked in period 25 (Jan 2025).
-- mart_cash_movements_by_period must count that refund as cash out in
-- period 26 (Feb 2025, by refund_date) rather than period 25 (by
-- invoice_date) — the exact bug mart_revenue_reconciliation_by_period's
-- billing_refunded_amount_against_bookings deliberately does NOT fix,
-- since that column answers a different question.
--
-- Left joins throughout, anchored on a fixed expected_refund_id: an
-- inner join here would make the test vacuously pass if refund_id=1
-- ever stopped existing (empty input, empty output, no failure row).
-- Fails if the refund is missing, its adjustment period is missing, or
-- the period's billing_cash_out doesn't cover at least its amount.
with expected as (
    select 1 as refund_id
),

refund as (
    select
        refund_id,
        adjustment_period_id,
        refund_amount
    from {{ ref('fct_period_close_adjustments') }}
    where refund_id = 1
),

checked as (
    select
        expected.refund_id,
        refund.adjustment_period_id,
        refund.refund_amount,
        cash_movements.billing_cash_out
    from expected
    left join refund on expected.refund_id = refund.refund_id
    left join {{ ref('mart_cash_movements_by_period') }} as cash_movements
        on refund.adjustment_period_id = cash_movements.period_id
)

select
    refund_id,
    adjustment_period_id,
    refund_amount,
    billing_cash_out
from checked
where
    adjustment_period_id is null
    or billing_cash_out is null
    or billing_cash_out < refund_amount
