with customers as (
    select * from {{ ref('stg_customers') }}
),

order_stats as (
    select
        customer_id,
        min(order_date) as first_order_date,
        max(order_date) as most_recent_order_date,
        count(*) as lifetime_order_count
    from {{ ref('stg_orders') }}
    where order_status = 'completed'
    group by customer_id
),

final as (
    select
        customers.customer_id,
        customers.customer_name,
        customers.email,
        customers.signup_date,
        customers.region,
        customers.country,
        order_stats.first_order_date,
        order_stats.most_recent_order_date,
        coalesce(order_stats.lifetime_order_count, 0) as lifetime_order_count
    from customers
    left join order_stats on customers.customer_id = order_stats.customer_id
)

select * from final
