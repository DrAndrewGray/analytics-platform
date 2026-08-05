with source as (
    select * from {{ source('billing', 'plans') }}
),

renamed as (
    select
        plan_id,
        plan_name,
        billing_interval,
        currency,
        price::numeric as price
    from source
)

select * from renamed
