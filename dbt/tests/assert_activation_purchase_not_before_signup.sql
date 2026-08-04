-- Regression test for a real bug: mart_activation's first_purchase_at
-- used to be a customer's globally-earliest purchase, which could
-- predate their signup entirely and still satisfy the 14-day activation
-- window by construction. first_purchase_at must never precede
-- first_signup_at.
select
    customer_id,
    first_signup_at,
    first_purchase_at
from {{ ref('mart_activation') }}
where
    first_purchase_at is not null
    and first_purchase_at < first_signup_at
