-- One row per subscription phase. subscription_chain_id groups the
-- phases that make up one customer's subscription history across
-- upgrades, downgrades, pauses, and reactivations.
select
    subscription_id,
    subscription_chain_id,
    customer_id,
    plan_id,
    plan_name,
    billing_interval,
    phase_start_date,
    phase_end_date,
    phase_type,
    is_trial,
    ended_reason,
    mrr_amount
from {{ ref('int_subscription_periods') }}
