with source as (
    select * from {{ source('raw', 'orders') }}
),

renamed as (
    select
        order_id,
        customer_id,
        order_date,
        status as order_status,
        channel as order_channel
    from source
)

select * from renamed
