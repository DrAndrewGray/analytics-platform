-- Structural check that int_events_deduplicated actually deduplicated:
-- no two rows in fct_events should share anonymous_id, event_type,
-- product_id, and event_timestamp.
select
    anonymous_id,
    event_type,
    event_timestamp,
    coalesce(product_id, -1) as product_id_key,
    count(*) as row_count
from {{ ref('fct_events') }}
group by anonymous_id, event_type, coalesce(product_id, -1), event_timestamp
having count(*) > 1
