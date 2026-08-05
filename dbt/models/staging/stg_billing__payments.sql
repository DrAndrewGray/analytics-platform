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
        -- Same double-precision gap as stg_payments/stg_billing__invoices etc:
        -- raw.amount loads as double precision, and this feeds sum()s in
        -- int_payment_refund_netting / int_invoice_payment_status / the
        -- Phase 4 cash-movement view. Missed in the original sweep because
        -- nothing had yet aggregated enough payment_amount rows to show
        -- visible drift.
        amount::numeric as payment_amount
    from source
)

select * from renamed
