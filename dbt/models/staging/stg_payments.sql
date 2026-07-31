with source as (
    select * from {{ source('raw', 'payments') }}
),

renamed as (
    select
        payment_id,
        order_id,
        payment_date,
        amount,
        payment_method,
        status as payment_status
    from source
)

select * from renamed
