with source as (
    select * from {{ source('billing', 'refunds') }}
),

renamed as (
    select
        refund_id,
        payment_id,
        refund_date,
        reason as refund_reason,
        amount::numeric as refund_amount
    from source
)

select * from renamed
