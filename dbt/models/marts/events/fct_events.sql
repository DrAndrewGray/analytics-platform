-- One row per event: deduplicated, identity-resolved, sessionized.
select
    event_id,
    anonymous_id,
    resolved_customer_id as customer_id,
    session_id,
    event_type,
    event_timestamp,
    product_id,
    order_id,
    search_query
from {{ ref('int_sessions') }}
