-- One row per month: total contracted MRR and how many chains/customers
-- were actually paying. Deliberately does not include cash-collected
-- figures — see fct_invoices / mart_invoice_reconciliation for that; MRR
-- is contracted value, not cash (docs/metric_definitions.md).
select
    activity_month,
    sum(mrr_amount) as total_mrr,
    count(distinct case when mrr_amount > 0 then subscription_chain_id end)
        as paying_subscription_count,
    count(distinct case when mrr_amount > 0 then customer_id end) as paying_customer_count
from {{ ref('int_subscription_mrr_by_chain_month') }}
group by 1
order by 1
