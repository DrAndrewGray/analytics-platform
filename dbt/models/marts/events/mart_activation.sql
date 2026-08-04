-- One row per customer who has ever signed up. is_activated: purchased
-- within 14 days of signup (docs/metric_definitions_events.md) — a
-- deliberately simple, single-threshold definition.
--
-- first_purchase_at is deliberately the first purchase *on or after*
-- signup, not the customer's globally-earliest purchase ever. A purchase
-- before signup (e.g. a guest checkout later followed by account
-- creation) says nothing about whether signing up led to a purchase,
-- and treating it as "first purchase" would produce a negative
-- days_to_first_purchase and could satisfy the 14-day window by
-- accident, marking a customer activated based on activity that happened
-- before they ever signed up.
with signups as (
    select
        resolved_customer_id as customer_id,
        min(event_timestamp) as first_signup_at
    from {{ ref('int_sessions') }}
    where event_type = 'signup' and resolved_customer_id is not null
    group by resolved_customer_id
),

purchases_after_signup as (
    select
        sessions.resolved_customer_id as customer_id,
        min(sessions.event_timestamp) as first_purchase_at
    from {{ ref('int_sessions') }} as sessions
    inner join signups on sessions.resolved_customer_id = signups.customer_id
    where
        sessions.event_type = 'purchase'
        and sessions.event_timestamp >= signups.first_signup_at
    group by sessions.resolved_customer_id
),

final as (
    select
        signups.customer_id,
        signups.first_signup_at,
        purchases_after_signup.first_purchase_at,
        extract(
            epoch from (purchases_after_signup.first_purchase_at - signups.first_signup_at)
        ) / 86400 as days_to_first_purchase,
        (
            purchases_after_signup.first_purchase_at is not null
            and purchases_after_signup.first_purchase_at <= signups.first_signup_at + interval '14 days'
        ) as is_activated
    from signups
    left join purchases_after_signup on signups.customer_id = purchases_after_signup.customer_id
)

select * from final
