with source as (
    select * from {{ source('events', 'events') }}
),

renamed as (
    select
        event_id,
        anonymous_id,
        customer_id,
        event_type,
        event_timestamp,
        product_id,
        order_id,
        search_query
    from source
)

select * from renamed
