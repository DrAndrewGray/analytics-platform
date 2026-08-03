-- The MRR bridge, one row per month:
--   opening_mrr + new + expansion + reactivation - contraction - churned = closing_mrr
-- computed_closing_mrr is that formula evaluated directly, so a mismatch
-- against closing_mrr is visible by eye here, not just in the dedicated
-- test (dbt/tests/assert_mrr_bridge_reconciles.sql).
--
-- GRR excludes expansion on purpose — it answers "how much would we have
-- kept with zero upsell," and can never exceed 100%. NRR includes it and
-- can exceed 100%. See docs/metric_definitions.md.
with movements as (
    select * from {{ ref('int_subscription_mrr_movements') }}
),

aggregated as (
    select
        activity_month,
        sum(prev_mrr_amount) as opening_mrr,
        sum(new_mrr) as new_mrr,
        sum(expansion_mrr) as expansion_mrr,
        sum(reactivation_mrr) as reactivation_mrr,
        sum(contraction_mrr) as contraction_mrr,
        sum(churned_mrr) as churned_mrr,
        sum(mrr_amount) as closing_mrr
    from movements
    group by activity_month
)

select
    activity_month,
    opening_mrr,
    new_mrr,
    expansion_mrr,
    reactivation_mrr,
    contraction_mrr,
    churned_mrr,
    closing_mrr,
    round(
        (opening_mrr + new_mrr + expansion_mrr + reactivation_mrr - contraction_mrr - churned_mrr)
        ::numeric,
        2
    ) as computed_closing_mrr,
    case
        when opening_mrr > 0
            then round(((opening_mrr - contraction_mrr - churned_mrr) / opening_mrr)::numeric, 4)
    end as gross_revenue_retention,
    case
        when opening_mrr > 0
            then round(
                (
                    (opening_mrr - contraction_mrr - churned_mrr + expansion_mrr) / opening_mrr
                )::numeric,
                4
            )
    end as net_revenue_retention
from aggregated
order by activity_month
