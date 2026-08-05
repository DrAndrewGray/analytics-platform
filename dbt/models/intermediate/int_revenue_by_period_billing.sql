-- Billing invoices assigned to their accounting period by invoice_date,
-- with tax computed from the customer's region. Aggregates fct_invoices'
-- own tested revenue numbers rather than re-deriving them.
--
-- collected_amount and refunded_amount_against_bookings are attributed
-- to the *invoice's* period, same as booked_revenue — i.e. "how much of
-- what was booked here has since been collected/refunded," not "how
-- much cash moved in this period." A payment or refund can land in a
-- later period than its invoice; see int_cash_movements_billing for the
-- by-payment-date/by-refund-date view of the same money.
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
        invoices.refunded_amount as refunded_amount_against_bookings,
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
