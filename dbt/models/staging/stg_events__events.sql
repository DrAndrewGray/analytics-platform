with source as (
    select * from {{ source('events', 'events') }}
),

renamed as (
    select
        event_id,
        anonymous_id,
        -- raw.events.customer_id/product_id/order_id load as double
        -- precision: these are nullable in the raw CSV (an anonymous
        -- visitor has no customer_id yet), and pandas upcasts an
        -- otherwise-integer column to float64 the moment it contains a
        -- NaN. Never caused visible drift (nothing sums an ID), but a
        -- foreign key stored as a float is still wrong on its own
        -- terms, and int_identity_resolution's max(customer_id) and any
        -- entity join against fct_orders/dim_customers should be
        -- joining bigint to bigint, not float to bigint.
        customer_id::bigint as customer_id,
        event_type,
        event_timestamp,
        product_id::bigint as product_id,
        order_id::bigint as order_id,
        search_query
    from source
)

select * from renamed
