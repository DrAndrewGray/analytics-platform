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
        -- raw_billing.invoices.amount loads as double precision; casting
        -- here avoids float drift once this gets summed across many rows
        -- downstream (same class of bug as stg_payments.amount).
        amount::numeric as invoice_amount
    from source
)

select * from renamed
