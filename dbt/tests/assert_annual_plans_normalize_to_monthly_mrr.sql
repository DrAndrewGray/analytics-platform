-- Every non-trial phase on an annual plan should contribute exactly
-- (annual price / 12), rounded to cents — the normalization rule from
-- docs/metric_definitions.md, checked directly rather than just trusted.
select
    fct_subscriptions.subscription_id,
    fct_subscriptions.mrr_amount,
    round((dim_plans.list_price / 12)::numeric, 2) as expected_mrr_amount
from {{ ref('fct_subscriptions') }} as fct_subscriptions
inner join {{ ref('dim_plans') }} as dim_plans on fct_subscriptions.plan_id = dim_plans.plan_id
where
    dim_plans.billing_interval = 'annual'
    and not fct_subscriptions.is_trial
    and fct_subscriptions.mrr_amount != round((dim_plans.list_price / 12)::numeric, 2)
