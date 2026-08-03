-- Classic cohort retention triangle: one row per (cohort_month,
-- months_since_cohort_start), showing what fraction of that cohort was
-- still an active, paying subscriber N months after joining. Cohort =
-- the calendar month of a chain's first-ever phase (trial or new) — see
-- docs/metric_definitions.md.
with cohort_start as (
    select
        subscription_chain_id,
        min(phase_start_date) as cohort_start_date
    from {{ ref('int_subscription_periods') }}
    where phase_type in ('trial', 'new')
    group by subscription_chain_id
),

cohort_month as (
    select
        subscription_chain_id,
        date_trunc('month', cohort_start_date)::date as cohort_month
    from cohort_start
),

mrr_by_month as (
    select * from {{ ref('int_subscription_mrr_by_chain_month') }}
),

joined as (
    select
        cohort_month.cohort_month,
        cohort_month.subscription_chain_id,
        (
            (extract(year from mrr_by_month.activity_month) - extract(year from cohort_month.cohort_month)) * 12
            + (extract(month from mrr_by_month.activity_month) - extract(month from cohort_month.cohort_month))
        )::int as months_since_cohort_start,
        mrr_by_month.mrr_amount > 0 as is_paying
    from cohort_month
    inner join mrr_by_month
        on cohort_month.subscription_chain_id = mrr_by_month.subscription_chain_id
    where mrr_by_month.activity_month >= cohort_month.cohort_month
),

cohort_sizes as (
    select
        cohort_month,
        count(distinct subscription_chain_id) as cohort_size
    from cohort_month
    group by cohort_month
),

retention as (
    select
        joined.cohort_month,
        joined.months_since_cohort_start,
        cohort_sizes.cohort_size,
        count(distinct case when joined.is_paying then joined.subscription_chain_id end)
            as active_chain_count,
        round(
            count(distinct case when joined.is_paying then joined.subscription_chain_id end)::numeric
            / nullif(cohort_sizes.cohort_size, 0),
            4
        ) as retention_rate
    from joined
    inner join cohort_sizes on joined.cohort_month = cohort_sizes.cohort_month
    group by joined.cohort_month, joined.months_since_cohort_start, cohort_sizes.cohort_size
)

select * from retention
order by cohort_month, months_since_cohort_start
