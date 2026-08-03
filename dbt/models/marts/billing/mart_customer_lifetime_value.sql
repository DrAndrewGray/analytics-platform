-- Single-row summary. estimated_clv = avg_mrr_per_active_customer /
-- monthly_churn_rate — the standard simple-CLV formula, which assumes
-- constant churn and MRR going forward. Both inputs are exposed
-- alongside the result on purpose: see docs/metric_definitions.md for
-- why this is documented as a simplification, not dressed up as more
-- rigorous than it is.
with movements as (
    select * from {{ ref('int_subscription_mrr_movements') }}
),

monthly_churn as (
    select
        activity_month,
        count(distinct case when churned_mrr > 0 then subscription_chain_id end) as churned_chains,
        count(distinct case when prev_mrr_amount > 0 then subscription_chain_id end)
            as chains_active_at_start
    from movements
    group by 1
),

churn_rate as (
    select
        avg(
            case
                when chains_active_at_start > 0
                    then churned_chains::numeric / chains_active_at_start
            end
        ) as monthly_churn_rate
    from monthly_churn
),

latest_month as (
    select max(activity_month) as activity_month from {{ ref('int_subscription_mrr_by_chain_month') }}
),

avg_mrr as (
    select avg(mrr_by_month.mrr_amount) as avg_mrr_per_active_customer
    from {{ ref('int_subscription_mrr_by_chain_month') }} as mrr_by_month
    inner join latest_month on mrr_by_month.activity_month = latest_month.activity_month
    where mrr_by_month.mrr_amount > 0
)

select
    latest_month.activity_month as as_of_month,
    round(avg_mrr.avg_mrr_per_active_customer::numeric, 2) as avg_mrr_per_active_customer,
    round(churn_rate.monthly_churn_rate::numeric, 4) as monthly_churn_rate,
    round(
        (avg_mrr.avg_mrr_per_active_customer / nullif(churn_rate.monthly_churn_rate, 0))::numeric,
        2
    ) as estimated_clv
from avg_mrr
cross join churn_rate
cross join latest_month
