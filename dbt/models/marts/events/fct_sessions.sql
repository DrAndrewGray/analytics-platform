-- One row per session (session grain, not event grain — see
-- int_sessions for the gap-based session definition).
select
    session_id,
    anonymous_id,
    resolved_customer_id as customer_id,
    min(event_timestamp) as session_start,
    max(event_timestamp) as session_end,
    count(*) as event_count,
    bool_or(event_type = 'purchase') as converted
from {{ ref('int_sessions') }}
group by session_id, anonymous_id, resolved_customer_id
