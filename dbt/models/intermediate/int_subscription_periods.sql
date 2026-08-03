-- One row per subscription phase, enriched with plan details and the
-- phase's MRR contribution. See docs/metric_definitions.md for the MRR
-- rules (annual normalization, trials contribute $0).
with subscriptions as (
    select * from {{ ref('stg_billing__subscriptions') }}
),

plans as (
    select * from {{ ref('stg_billing__plans') }}
),

enriched as (
    select
        subscriptions.subscription_id,
        subscriptions.subscription_chain_id,
        subscriptions.customer_id,
        subscriptions.plan_id,
        plans.plan_name,
        plans.billing_interval,
        subscriptions.phase_start_date,
        subscriptions.phase_end_date,
        subscriptions.phase_type,
        subscriptions.is_trial,
        subscriptions.ended_reason,
        -- Every branch cast to numeric explicitly: mixing numeric and
        -- double precision branches in one CASE resolves the whole column
        -- to double precision, which reintroduces exactly the kind of
        -- float drift (e.g. 19.99 - 9.99 = 9.999999999999998) the Phase 1
        -- Decimal fix was written to avoid.
        case
            when subscriptions.is_trial then 0::numeric
            when plans.billing_interval = 'annual' then round((plans.price / 12)::numeric, 2)
            else round(plans.price::numeric, 2)
        end as mrr_amount
    from subscriptions
    inner join plans on subscriptions.plan_id = plans.plan_id
)

select * from enriched
