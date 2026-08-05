-- One row per billing refund, annotated with period-close-adjustment
-- context. Not filtered to late adjustments only — filter on
-- is_late_adjustment yourself, same reasoning as fct_orders keeping
-- cancelled/refunded rows instead of filtering them upstream.
select
    refund_id,
    invoice_id,
    invoice_date,
    refund_date,
    refund_amount,
    original_period_id,
    adjustment_period_id,
    original_period_closed_at,
    is_late_adjustment,
    days_after_close
from {{ ref('int_period_close_adjustments') }}
