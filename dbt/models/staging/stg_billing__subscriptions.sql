with source as (
    select * from {{ source('billing', 'subscriptions') }}
),

renamed as (
    select
        subscription_id,
        subscription_chain_id,
        customer_id,
        plan_id,
        phase_start_date,
        phase_end_date,
        phase_type,
        is_trial,
        ended_reason
    from source
)

select * from renamed
