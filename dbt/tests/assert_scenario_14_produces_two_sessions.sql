-- Named-scenario test (see scripts/generate_event_data.py, customer 14):
-- a 2-hour gap between events for the same anonymous_id must produce
-- exactly two sessions, not one — the whole point of sessionization.
-- Fails (returns a row) if that's not what happened.
select
    customer_id,
    count(distinct session_id) as session_count
from {{ ref('fct_events') }}
where customer_id = 14
group by customer_id
having count(distinct session_id) != 2
