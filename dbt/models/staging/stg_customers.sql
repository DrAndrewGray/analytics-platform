with source as (
    select * from {{ source('raw', 'customers') }}
),

renamed as (
    select
        customer_id,
        first_name,
        last_name,
        signup_date,
        region,
        country,
        lower(email) as email,
        first_name || ' ' || last_name as customer_name
    from source
)

select * from renamed
