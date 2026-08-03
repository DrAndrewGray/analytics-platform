-- One row per payment attempt, netted against any refunds against it.
select
    payment_id,
    invoice_id,
    payment_date,
    payment_status,
    payment_method,
    is_retry,
    payment_amount,
    refunded_amount,
    net_collected_amount
from {{ ref('int_payment_refund_netting') }}
