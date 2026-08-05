-- Singular test: named scenario customer 7 (scripts/generate_billing_data.py)
-- has a refund deliberately delayed past its period's close date. This
-- guards the is_late_adjustment branch itself having a positive proof
-- case, not just structural columns — same reasoning as
-- assert_scenario_14_produces_two_sessions.sql for identity resolution.
-- Fails (returns a row) if no late adjustment exists at all.
select count(*) as late_adjustment_count
from {{ ref('fct_period_close_adjustments') }}
where is_late_adjustment
having count(*) = 0
