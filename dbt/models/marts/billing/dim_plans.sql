select
    plan_id,
    plan_name,
    billing_interval,
    currency,
    price as list_price,
    case
        when billing_interval = 'annual' then round((price / 12)::numeric, 2)
        else round(price::numeric, 2)
    end as monthly_equivalent_price
from {{ ref('stg_billing__plans') }}
