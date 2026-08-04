-- int_identity_resolution uses max(customer_id) per anonymous_id, which
-- is only correct if each anonymous_id ever carries at most one distinct
-- non-null customer_id. This checks that assumption directly rather than
-- letting a violation silently pick an arbitrary customer_id via max().
select
    anonymous_id,
    count(distinct customer_id) as distinct_customer_count
from {{ ref('stg_events__events') }}
where customer_id is not null
group by anonymous_id
having count(distinct customer_id) > 1
