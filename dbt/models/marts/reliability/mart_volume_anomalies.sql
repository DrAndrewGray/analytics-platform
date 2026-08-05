-- One row per source per accounting period: row-count volume compared
-- against a 3-period trailing average. is_anomaly and is_eligible_for_check
-- are precomputed here (not just left to the singular test) so this mart
-- is directly queryable as a health-report input on its own — see
-- scripts/generate_health_report.py.
--
-- Threshold (-40%) and eligibility floor (trailing_avg_row_count >= 10)
-- are both calibrated from this warehouse's own history: across every
-- closed period with a trailing average of at least 10 rows, the worst
-- real month-over-month drop on record is -19.1% (orders, Feb 2025).
-- -40% leaves more than 2x margin below anything this dataset has ever
-- legitimately done, while still catching an injected near-total volume
-- collapse (see docs/incidents/). See docs/reliability_strategy.md for
-- why period-grain, not day-grain, and why only closed periods count.
select
    source_name,
    period_id,
    period_start_date,
    is_closed,
    row_count,
    trailing_avg_row_count,
    pct_change_vs_trailing_avg,
    (trailing_avg_row_count >= 10) as is_eligible_for_check,
    (
        is_closed
        and trailing_avg_row_count >= 10
        and pct_change_vs_trailing_avg <= -40
    ) as is_anomaly
from {{ ref('int_volume_anomaly_by_period') }}
order by source_name, period_id
