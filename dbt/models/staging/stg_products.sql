with source as (
    select * from {{ source('raw', 'products') }}
),

renamed as (
    select
        product_id,
        product_name,
        category,
        unit_cost::numeric as unit_cost,
        unit_price::numeric as unit_price,
        is_active,
        round((unit_price - unit_cost)::numeric, 2) as unit_margin
    from source
)

select * from renamed
