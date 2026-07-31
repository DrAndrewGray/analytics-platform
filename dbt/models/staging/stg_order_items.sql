with source as (
    select * from {{ source('raw', 'order_items') }}
),

renamed as (
    select
        order_item_id,
        order_id,
        product_id,
        quantity,
        unit_price,
        coalesce(discount, 0) as discount,
        round((quantity * unit_price * (1 - coalesce(discount, 0)))::numeric, 2) as line_amount
    from source
)

select * from renamed
