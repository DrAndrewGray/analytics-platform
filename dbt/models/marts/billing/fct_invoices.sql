-- One row per invoice. outstanding_balance is the reconciliation
-- number — see docs/metric_definitions.md.
select
    invoice_id,
    subscription_id,
    customer_id,
    invoice_date,
    invoice_amount,
    payment_attempt_count,
    has_succeeded_payment,
    has_failed_attempt,
    net_collected_amount,
    refunded_amount,
    last_payment_date,
    outstanding_balance
from {{ ref('int_invoice_payment_status') }}
