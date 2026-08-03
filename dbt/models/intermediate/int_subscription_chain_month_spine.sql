-- One row per (subscription_chain_id, calendar month) from that chain's
-- first-ever phase through the latest month we have real billing data
-- for. Every month is represented, including ones where the chain had no
-- active phase — MRR-movement classification (int_subscription_mrr_movements)
-- depends on there being no gaps, so churn/reactivation can be detected by
-- comparing strictly consecutive calendar months, not just consecutive rows.
with chains as (
    select
        subscription_chain_id,
        customer_id,
        min(phase_start_date) as chain_first_start
    from {{ ref('int_subscription_periods') }}
    group by 1, 2
),

bounds as (
    -- Bounded by actual billing data, not current_date: an "ongoing" phase
    -- shouldn't gain extra active months just because real time passed
    -- since the data was generated, with no corresponding invoice to show
    -- for it.
    select max(period_end) as data_max_date
    from {{ ref('stg_billing__invoices') }}
),

spine as (
    select
        chains.subscription_chain_id,
        chains.customer_id,
        date_trunc('month', month_start)::date as activity_month
    from chains
    cross join bounds
    cross join lateral generate_series(
        date_trunc('month', chains.chain_first_start),
        date_trunc('month', bounds.data_max_date),
        interval '1 month'
    ) as month_start
)

select * from spine
