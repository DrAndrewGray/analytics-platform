-- Singular test: days_after_close should be populated if and only if
-- is_late_adjustment is true, and always positive when populated.
-- Guards against the two columns drifting apart from their shared
-- condition in int_period_close_adjustments.sql.
select
    refund_id,
    is_late_adjustment,
    days_after_close
from {{ ref('fct_period_close_adjustments') }}
where
    (is_late_adjustment and (days_after_close is null or days_after_close <= 0))
    or (not is_late_adjustment and days_after_close is not null)
