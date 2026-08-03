-- One row per (subscription_chain_id, calendar month), covering every
-- month from the chain's first activity through the latest known billing
-- data — including months with $0 MRR (inactive, or trialing).
--
-- When two phases of the same chain are both active in a month (a trial
-- ending and the paid phase starting mid-month), the chronologically
-- later phase is authoritative for that month: it reflects the state the
-- chain carries into the following month, which is what the movement
-- classification (int_subscription_mrr_movements) needs to be correct.
with active_phase_months as (
    select * from {{ ref('int_subscription_active_phase_months') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by subscription_chain_id, activity_month
            order by phase_start_date desc, subscription_id desc
        ) as rn
    from active_phase_months
),

authoritative as (
    select
        subscription_chain_id,
        customer_id,
        activity_month,
        plan_id,
        mrr_amount
    from ranked
    where rn = 1
),

spine as (
    select * from {{ ref('int_subscription_chain_month_spine') }}
),

final as (
    select
        spine.subscription_chain_id,
        spine.customer_id,
        spine.activity_month,
        authoritative.plan_id,
        coalesce(authoritative.mrr_amount, 0::numeric) as mrr_amount
    from spine
    left join authoritative
        on
            spine.subscription_chain_id = authoritative.subscription_chain_id
            and spine.activity_month = authoritative.activity_month
)

select * from final
