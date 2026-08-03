-- Classifies each chain-month's change in MRR versus the *literal*
-- previous calendar month (guaranteed to exist as a row, at $0 if
-- inactive, thanks to int_subscription_chain_month_spine having no
-- gaps). See docs/metric_definitions.md for the movement definitions and
-- the bridge invariant this feeds (tested in
-- dbt/tests/assert_mrr_bridge_reconciles.sql).
with mrr_by_month as (
    select * from {{ ref('int_subscription_mrr_by_chain_month') }}
),

with_history as (
    select
        *,
        lag(mrr_amount) over (
            partition by subscription_chain_id order by activity_month
        ) as prev_mrr_amount,
        -- Was this chain ever paying (mrr > 0) in a *strictly earlier*
        -- month? Distinguishes "New" (never paid before) from
        -- "Reactivation" (paid, stopped, now paying again).
        coalesce(
            bool_or(mrr_amount > 0) over (
                partition by subscription_chain_id
                order by activity_month
                rows between unbounded preceding and 1 preceding
            ),
            false
        ) as was_ever_paying_before
    from mrr_by_month
),

classified as (
    select
        subscription_chain_id,
        customer_id,
        activity_month,
        mrr_amount,
        coalesce(prev_mrr_amount, 0) as prev_mrr_amount,
        case
            when coalesce(prev_mrr_amount, 0) = 0 and mrr_amount > 0 and not was_ever_paying_before
                then mrr_amount
            else 0
        end as new_mrr,
        case
            when coalesce(prev_mrr_amount, 0) = 0 and mrr_amount > 0 and was_ever_paying_before
                then mrr_amount
            else 0
        end as reactivation_mrr,
        case
            when prev_mrr_amount > 0 and mrr_amount > prev_mrr_amount
                then mrr_amount - prev_mrr_amount
            else 0
        end as expansion_mrr,
        case
            when prev_mrr_amount > 0 and mrr_amount < prev_mrr_amount and mrr_amount > 0
                then prev_mrr_amount - mrr_amount
            else 0
        end as contraction_mrr,
        case
            when prev_mrr_amount > 0 and mrr_amount = 0
                then prev_mrr_amount
            else 0
        end as churned_mrr
    from with_history
)

select * from classified
