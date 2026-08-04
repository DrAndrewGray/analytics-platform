-- One row per day: how many distinct visitors reached each funnel step
-- (docs/metric_definitions_events.md), and the conversion rate between
-- consecutive steps. visitor_key unifies a visitor's activity under
-- their resolved customer_id once known, so pre- and post-identification
-- activity from the same anonymous_id isn't double-counted as two
-- separate visitors.
with sessions as (
    select * from {{ ref('int_sessions') }}
),

visitor_days as (
    select
        date_trunc('day', event_timestamp)::date as activity_date,
        coalesce(resolved_customer_id::text, anonymous_id) as visitor_key,
        bool_or(event_type = 'product_view') as viewed,
        bool_or(event_type = 'add_to_cart') as added_to_cart,
        bool_or(event_type = 'checkout_start') as started_checkout,
        bool_or(event_type = 'purchase') as purchased
    from sessions
    group by activity_date, visitor_key
),

daily as (
    select
        activity_date,
        count(distinct case when viewed then visitor_key end) as viewers,
        count(distinct case when added_to_cart then visitor_key end) as carters,
        count(distinct case when started_checkout then visitor_key end) as checkout_starters,
        count(distinct case when purchased then visitor_key end) as purchasers
    from visitor_days
    group by activity_date
)

select
    activity_date,
    viewers,
    carters,
    checkout_starters,
    purchasers,
    case when viewers > 0 then round(carters::numeric / viewers, 4) end as view_to_cart_rate,
    case when carters > 0 then round(checkout_starters::numeric / carters, 4) end as cart_to_checkout_rate,
    case
        when checkout_starters > 0 then round(purchasers::numeric / checkout_starters, 4)
    end as checkout_to_purchase_rate,
    case when viewers > 0 then round(purchasers::numeric / viewers, 4) end as view_to_purchase_rate
from daily
order by activity_date
