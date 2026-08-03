with source as (
    select * from {{ source('billing', 'invoices') }}
),

renamed as (
    select
        invoice_id,
        subscription_id,
        customer_id,
        invoice_date,
        period_start,
        period_end,
        amount as invoice_amount
    from source
)

select * from renamed
