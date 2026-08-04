-- Drops exact duplicate events (same anonymous_id, event_type,
-- product_id, and event_timestamp) — see docs/metric_definitions_events.md
-- for why this is deliberately an exact match, not a fuzzy time window.
-- coalesce(product_id, -1) so two product-less events (e.g. two
-- page_views) aren't compared as "both null, therefore equal" by accident
-- across postgres's null-is-distinct-from-null semantics working in our
-- favor here, then immediately relied on incorrectly elsewhere.
with resolved as (
    select * from {{ ref('int_events_resolved') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by anonymous_id, event_type, coalesce(product_id, -1), event_timestamp
            order by event_id
        ) as dedup_rank
    from resolved
)

select
    event_id,
    anonymous_id,
    resolved_customer_id,
    event_type,
    event_timestamp,
    product_id,
    order_id,
    search_query
from ranked
where dedup_rank = 1
