select
    product_id,
    product_name,
    category,
    unit_cost,
    unit_price,
    unit_margin,
    is_active
from {{ ref('stg_products') }}
