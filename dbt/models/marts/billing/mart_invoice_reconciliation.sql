-- One row per month: invoiced vs. collected vs. refunded vs. outstanding.
-- The billing-domain analogue of Phase 1's order-level reconciliation,
-- rolled up to a grain someone can actually eyeball across a year.
select
    date_trunc('month', invoice_date)::date as activity_month,
    count(*) as invoice_count,
    sum(invoice_amount) as invoiced_amount,
    sum(net_collected_amount) as collected_amount,
    sum(refunded_amount) as refunded_amount,
    sum(outstanding_balance) as outstanding_amount
from {{ ref('int_invoice_payment_status') }}
group by 1
order by 1
