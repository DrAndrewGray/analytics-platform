with source as (
    select * from {{ source('billing', 'invoice_lines') }}
),

renamed as (
    select
        invoice_line_id,
        invoice_id,
        subscription_id,
        description,
        quantity,
        unit_amount::numeric as unit_amount,
        amount::numeric as line_amount
    from source
)

select * from renamed
