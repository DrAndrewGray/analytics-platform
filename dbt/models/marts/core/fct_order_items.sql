-- Line-item grain fact table, for questions fct_orders can't answer
-- (product mix, category performance, discount impact per line).
select
    order_item_id,
    order_id,
    customer_id,
    order_date,
    order_status,
    order_channel,
    product_id,
    product_category,
    quantity,
    unit_price,
    discount,
    line_amount
from {{ ref('int_order_items_enriched') }}
