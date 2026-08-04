-- Every event, including ones that happened before the visitor was ever
-- identified, gets the fully resolved customer_id — the whole point of
-- separating identity resolution from the raw event stream.
select
    events.event_id,
    events.anonymous_id,
    identity_map.resolved_customer_id,
    events.event_type,
    events.event_timestamp,
    events.product_id,
    events.order_id,
    events.search_query
from {{ ref('stg_events__events') }} as events
left join {{ ref('int_identity_resolution') }} as identity_map
    on events.anonymous_id = identity_map.anonymous_id
