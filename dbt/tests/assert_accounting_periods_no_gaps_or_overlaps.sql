-- Singular test: accounting_periods must form a gap-free, non-overlapping
-- monthly sequence when ordered by period_start_date. Every period's end
-- date should be exactly one day before the next period's start date.
-- Fails (returns a row) for any period whose successor doesn't line up.
with ordered as (
    select
        period_id,
        period_start_date,
        period_end_date,
        lead(period_start_date) over (order by period_start_date) as next_period_start_date
    from {{ ref('accounting_periods') }}
)

select
    period_id,
    period_end_date,
    next_period_start_date
from ordered
where
    next_period_start_date is not null
    and next_period_start_date != period_end_date + 1
