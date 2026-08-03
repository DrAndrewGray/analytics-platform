with source as (
    select * from {{ source('billing', 'payments') }}
),

renamed as (
    select
        payment_id,
        invoice_id,
        payment_date,
        payment_method,
        is_retry,
        status as payment_status,
        amount as payment_amount
    from source
)

select * from renamed
