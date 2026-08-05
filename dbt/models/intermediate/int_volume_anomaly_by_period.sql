-- Trailing-average volume comparison per source per period. Zero-fills
-- gaps within each source's own active range (its first period with any
-- data through the warehouse's latest period) rather than only using
-- int_volume_by_period's inner-joined rows directly: a period where a
-- source's volume falls all the way to zero still needs a row here, or
-- "the source stopped loading entirely" would silently vanish from the
-- series instead of showing up as the most extreme possible drop.
-- Periods before a source's own first appearance are excluded, so a
-- domain's cold start (e.g. events/billing not existing in 2023) is
-- never itself flagged as an anomaly.
with volume as (
    select * from {{ ref('int_volume_by_period') }}
),

periods as (
    select * from {{ ref('dim_accounting_periods') }}
),

domain_bounds as (
    select
        source_name,
        min(period_id) as first_period_id,
        max(period_id) as last_period_id
    from volume
    group by source_name
),

expected as (
    select
        domain_bounds.source_name,
        periods.period_id
    from domain_bounds
    inner join periods
        on periods.period_id between domain_bounds.first_period_id and domain_bounds.last_period_id
),

filled as (
    select
        expected.source_name,
        expected.period_id,
        coalesce(volume.row_count, 0) as row_count
    from expected
    left join volume
        on
            expected.source_name = volume.source_name
            and expected.period_id = volume.period_id
),

with_trailing as (
    select
        filled.source_name,
        filled.period_id,
        periods.period_start_date,
        periods.is_closed,
        filled.row_count,
        avg(filled.row_count) over (
            partition by filled.source_name order by filled.period_id
            rows between 3 preceding and 1 preceding
        ) as trailing_avg_row_count
    from filled
    inner join periods on filled.period_id = periods.period_id
)

select
    source_name,
    period_id,
    period_start_date,
    is_closed,
    row_count,
    round(trailing_avg_row_count::numeric, 1) as trailing_avg_row_count,
    case
        when trailing_avg_row_count > 0
            then round(
                ((row_count - trailing_avg_row_count) / trailing_avg_row_count * 100)::numeric, 1
            )
    end as pct_change_vs_trailing_avg
from with_trailing
