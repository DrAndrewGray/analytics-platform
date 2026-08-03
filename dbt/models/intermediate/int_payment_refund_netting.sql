-- One row per payment, netted against any refunds against it.
-- net_collected_amount is what actually stayed in the business for that
-- payment — the number that should feed cash-collected metrics, not the
-- raw payment amount.
with payments as (
    select * from {{ ref('stg_billing__payments') }}
),

refunds as (
    select
        payment_id,
        sum(refund_amount) as total_refunded
    from {{ ref('stg_billing__refunds') }}
    group by 1
),

final as (
    select
        payments.payment_id,
        payments.invoice_id,
        payments.payment_date,
        payments.payment_status,
        payments.payment_method,
        payments.is_retry,
        payments.payment_amount,
        coalesce(refunds.total_refunded, 0) as refunded_amount,
        payments.payment_amount - coalesce(refunds.total_refunded, 0) as net_collected_amount
    from payments
    left join refunds on payments.payment_id = refunds.payment_id
)

select * from final
