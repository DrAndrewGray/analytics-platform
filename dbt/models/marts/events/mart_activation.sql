-- One row per customer who has ever signed up. is_activated: purchased
-- within 14 days of signup (docs/metric_definitions_events.md) — a
-- deliberately simple, single-threshold definition.
with signups as (
    select
        resolved_customer_id as customer_id,
        min(event_timestamp) as first_signup_at
    from {{ ref('int_sessions') }}
    where event_type = 'signup' and resolved_customer_id is not null
    group by 1
),

purchases as (
    select
        resolved_customer_id as customer_id,
        min(event_timestamp) as first_purchase_at
    from {{ ref('int_sessions') }}
    where event_type = 'purchase' and resolved_customer_id is not null
    group by 1
),

final as (
    select
        signups.customer_id,
        signups.first_signup_at,
        purchases.first_purchase_at,
        extract(epoch from (purchases.first_purchase_at - signups.first_signup_at)) / 86400
            as days_to_first_purchase,
        (
            purchases.first_purchase_at is not null
            and purchases.first_purchase_at <= signups.first_signup_at + interval '14 days'
        ) as is_activated
    from signups
    left join purchases on signups.customer_id = purchases.customer_id
)

select * from final
