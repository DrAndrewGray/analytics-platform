-- Order items joined to product and order context, still at line-item grain.
with order_items as (
    select * from {{ ref('stg_order_items') }}
),

orders as (
    select * from {{ ref('stg_orders') }}
),

products as (
    select * from {{ ref('stg_products') }}
),

joined as (
    select
        order_items.order_item_id,
        order_items.order_id,
        orders.customer_id,
        orders.order_date,
        orders.order_status,
        orders.order_channel,
        order_items.product_id,
        products.category as product_category,
        order_items.quantity,
        order_items.unit_price,
        order_items.discount,
        order_items.line_amount
    from order_items
    inner join orders on order_items.order_id = orders.order_id
    inner join products on order_items.product_id = products.product_id
)

select * from joined
