-- One row per order. Revenue reflects completed orders only; cancelled and
-- refunded orders are retained (not filtered out) so downstream consumers
-- can explicitly choose to include or exclude them rather than have that
-- decision made silently upstream.
with orders as (
    select * from {{ ref('stg_orders') }}
),

order_items as (
    select
        order_id,
        sum(quantity) as item_quantity,
        sum(line_amount) as order_amount
    from {{ ref('stg_order_items') }}
    group by order_id
),

payment_summary as (
    select * from {{ ref('int_order_payment_summary') }}
),

final as (
    select
        orders.order_id,
        orders.customer_id,
        orders.order_date,
        orders.order_status,
        orders.order_channel,
        coalesce(order_items.item_quantity, 0) as item_quantity,
        coalesce(order_items.order_amount, 0) as order_amount,
        coalesce(payment_summary.amount_collected, 0) as amount_collected,
        coalesce(payment_summary.payment_attempt_count, 0) as payment_attempt_count,
        coalesce(payment_summary.has_succeeded_payment, false) as has_succeeded_payment,
        round(
            (coalesce(order_items.order_amount, 0) - coalesce(payment_summary.amount_collected, 0))::numeric,
            2
        ) as revenue_minus_collected_variance
    from orders
    left join order_items on orders.order_id = order_items.order_id
    left join payment_summary on orders.order_id = payment_summary.order_id
)

select * from final
