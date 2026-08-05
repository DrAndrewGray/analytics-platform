-- Billing invoices assigned to their accounting period by invoice_date,
-- with tax computed from the customer's region. Aggregates fct_invoices'
-- own tested revenue numbers rather than re-deriving them.
with invoices as (
    select * from {{ ref('fct_invoices') }}
),

customers as (
    select
        customer_id,
        region
    from {{ ref('dim_customers') }}
),

tax_rates as (
    select * from {{ ref('tax_rates') }}
),

periods as (
    select * from {{ ref('accounting_periods') }}
),

joined as (
    select
        invoices.invoice_id,
        invoices.customer_id,
        invoices.invoice_date,
        periods.period_id,
        invoices.invoice_amount as booked_revenue,
        invoices.net_collected_amount as collected_amount,
        invoices.refunded_amount,
        round((invoices.invoice_amount * coalesce(tax_rates.tax_rate, 0))::numeric, 2)
            as tax_amount
    from invoices
    inner join customers on invoices.customer_id = customers.customer_id
    left join tax_rates on customers.region = tax_rates.region
    inner join periods
        on
            invoices.invoice_date >= periods.period_start_date
            and invoices.invoice_date <= periods.period_end_date
)

select * from joined
