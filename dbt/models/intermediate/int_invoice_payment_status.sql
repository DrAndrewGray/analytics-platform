-- One row per invoice, summarizing payment/refund activity against it.
-- outstanding_balance is the reconciliation number: invoiced amount
-- minus net cash actually collected. Zero means fully settled; nonzero
-- means underpaid, failed, refunded-past-payment, or not-yet-paid — the
-- invoice-level analogue of Phase 1's revenue_minus_collected_variance.
with invoices as (
    select * from {{ ref('stg_billing__invoices') }}
),

netting as (
    select * from {{ ref('int_payment_refund_netting') }}
),

payment_summary as (
    select
        invoice_id,
        count(*) as payment_attempt_count,
        bool_or(payment_status = 'succeeded') as has_succeeded_payment,
        bool_or(payment_status = 'failed') as has_failed_attempt,
        sum(case when payment_status = 'succeeded' then net_collected_amount else 0 end)
            as net_collected_amount,
        sum(case when payment_status = 'succeeded' then refunded_amount else 0 end)
            as refunded_amount,
        max(payment_date) as last_payment_date
    from netting
    group by 1
),

final as (
    select
        invoices.invoice_id,
        invoices.subscription_id,
        invoices.customer_id,
        invoices.invoice_date,
        invoices.invoice_amount,
        payment_summary.last_payment_date,
        coalesce(payment_summary.payment_attempt_count, 0) as payment_attempt_count,
        coalesce(payment_summary.has_succeeded_payment, false) as has_succeeded_payment,
        coalesce(payment_summary.has_failed_attempt, false) as has_failed_attempt,
        coalesce(payment_summary.net_collected_amount, 0) as net_collected_amount,
        coalesce(payment_summary.refunded_amount, 0) as refunded_amount,
        invoices.invoice_amount - coalesce(payment_summary.net_collected_amount, 0)
            as outstanding_balance
    from invoices
    left join payment_summary on invoices.invoice_id = payment_summary.invoice_id
)

select * from final
