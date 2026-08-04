-- Sessionizes the deduplicated, identity-resolved event stream: a new
-- session starts whenever the gap since the same anonymous_id's previous
-- event exceeds 30 minutes (docs/metric_definitions_events.md). Computed
-- on anonymous_id, not resolved_customer_id — sessions aren't merged
-- across different anonymous_ids that later resolve to the same
-- customer, since each anonymous_id is a distinct client that generated
-- its own contiguous burst of activity.
with deduped as (
    select * from {{ ref('int_events_deduplicated') }}
),

with_gaps as (
    select
        *,
        extract(
            epoch from (
                event_timestamp
                - lag(event_timestamp) over (partition by anonymous_id order by event_timestamp, event_id)
            )
        ) / 60 as minutes_since_previous_event
    from deduped
),

session_boundaries as (
    select
        *,
        case
            when minutes_since_previous_event is null or minutes_since_previous_event > 30 then 1
            else 0
        end as is_new_session
    from with_gaps
),

numbered as (
    select
        *,
        sum(is_new_session) over (
            partition by anonymous_id
            order by event_timestamp, event_id
            rows between unbounded preceding and current row
        ) as session_number
    from session_boundaries
)

select
    event_id,
    anonymous_id,
    resolved_customer_id,
    event_type,
    event_timestamp,
    product_id,
    order_id,
    search_query,
    anonymous_id || '_' || session_number::text as session_id
from numbered
