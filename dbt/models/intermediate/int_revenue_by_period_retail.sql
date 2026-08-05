-- Retail orders (completed only — see docs/business_context_finance.md)
-- assigned to their accounting period by order_date, with tax computed
-- from the customer's region. Aggregates fct_orders' own tested revenue
-- numbers rather than re-deriving them from raw tables.
--
-- No refunded_amount column here, unlike billing: a refunded retail
-- order never has order_status = 'completed', so it's excluded from
-- booked_revenue entirely rather than booked and later netted against a
-- refund. tax_amount is a separate illustrative line, not included in
-- booked_revenue or collected_amount — both of those are net-of-tax.
with orders as (
    select * from {{ ref('fct_orders') }}
    where order_status = 'completed'
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
        orders.order_id,
        orders.customer_id,
        orders.order_date,
        periods.period_id,
        orders.order_amount as booked_revenue,
        orders.amount_collected as collected_amount,
        round((orders.order_amount * coalesce(tax_rates.tax_rate, 0))::numeric, 2) as tax_amount
    from orders
    inner join customers on orders.customer_id = customers.customer_id
    left join tax_rates on customers.region = tax_rates.region
    inner join periods
        on
            orders.order_date >= periods.period_start_date
            and orders.order_date <= periods.period_end_date
)

select * from joined
