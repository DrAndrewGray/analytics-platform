with source as (
    select * from {{ source('raw', 'payments') }}
),

renamed as (
    select
        payment_id,
        order_id,
        payment_date,
        payment_method,
        status as payment_status,
        -- raw.payments.amount loads as double precision (pandas float64,
        -- never cast); summing many rows of that in int_order_payment_summary
        -- accumulates visible float drift (e.g. 2331.8599999999997) that a
        -- single-row test would never catch. Casting here, at the staging
        -- boundary, fixes it for every downstream consumer at once rather
        -- than requiring each aggregation site to remember to cast.
        amount::numeric as amount
    from source
)

select * from renamed
