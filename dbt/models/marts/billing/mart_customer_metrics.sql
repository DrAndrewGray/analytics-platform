-- One row per customer who has ever had a Meridian+ subscription.
-- is_currently_active means they have a phase with no end date — a
-- customer who paused or cancelled and never reactivated is not active,
-- even though they were once a subscriber.
with periods as (
    select * from {{ ref('int_subscription_periods') }}
),

subscription_summary as (
    select
        customer_id,
        min(phase_start_date) as first_subscription_date,
        bool_or(phase_end_date is null) as is_currently_active
    from periods
    group by 1
),

billing_summary as (
    select
        customer_id,
        sum(invoice_amount) as lifetime_invoiced_amount,
        sum(net_collected_amount) as lifetime_collected_amount,
        sum(refunded_amount) as lifetime_refunded_amount
    from {{ ref('int_invoice_payment_status') }}
    group by 1
),

bounds as (
    select max(period_end) as data_max_date from {{ ref('stg_billing__invoices') }}
),

final as (
    select
        subscription_summary.customer_id,
        subscription_summary.first_subscription_date,
        subscription_summary.is_currently_active,
        (
            (
                extract(year from bounds.data_max_date)
                - extract(year from subscription_summary.first_subscription_date)
            ) * 12
            + (
                extract(month from bounds.data_max_date)
                - extract(month from subscription_summary.first_subscription_date)
            )
        )::int as tenure_months,
        coalesce(billing_summary.lifetime_invoiced_amount, 0) as lifetime_invoiced_amount,
        coalesce(billing_summary.lifetime_collected_amount, 0) as lifetime_collected_amount,
        coalesce(billing_summary.lifetime_refunded_amount, 0) as lifetime_refunded_amount
    from subscription_summary
    cross join bounds
    left join billing_summary on subscription_summary.customer_id = billing_summary.customer_id
)

select * from final
