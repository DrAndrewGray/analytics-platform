-- One row per order, summarizing payment attempts against it.
-- Surfaces reconciliation-relevant facts: how many attempts, whether any
-- succeeded, and the total amount actually collected.
with payments as (
    select * from {{ ref('stg_payments') }}
),

aggregated as (
    select
        order_id,
        count(*) as payment_attempt_count,
        sum(case when payment_status = 'succeeded' then amount else 0 end) as amount_collected,
        bool_or(payment_status = 'succeeded') as has_succeeded_payment,
        bool_or(payment_status = 'failed') as has_failed_attempt,
        max(payment_date) as last_payment_date
    from payments
    group by order_id
)

select * from aggregated
