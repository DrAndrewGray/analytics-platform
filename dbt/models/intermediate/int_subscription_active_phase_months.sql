-- Each phase exploded into one row per calendar month it was active.
-- A phase active for any part of a month contributes for the whole
-- month (no proration) — see docs/metric_definitions.md.
--
-- Two phases of the same chain can both be active in the same month
-- (e.g. a trial ending and the paid phase starting mid-month); this
-- model doesn't resolve that yet, deliberately — see
-- int_subscription_mrr_by_chain_month for how the "authoritative" phase
-- for a given month is chosen.
with periods as (
    select * from {{ ref('int_subscription_periods') }}
),

bounds as (
    select max(period_end) as data_max_date
    from {{ ref('stg_billing__invoices') }}
),

exploded as (
    select
        periods.subscription_id,
        periods.subscription_chain_id,
        periods.customer_id,
        periods.plan_id,
        periods.mrr_amount,
        periods.phase_start_date,
        date_trunc('month', month_start)::date as activity_month
    from periods
    cross join bounds
    cross join lateral generate_series(
        date_trunc('month', periods.phase_start_date),
        date_trunc('month', coalesce(periods.phase_end_date, bounds.data_max_date) - interval '1 day'),
        interval '1 month'
    ) as month_start
)

select * from exploded
