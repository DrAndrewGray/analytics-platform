-- One row per (period, customer) pair where that customer was "active" —
-- engaged with either revenue line during that accounting period. This
-- is a deliberate, single governed definition (see
-- docs/metric_definitions_semantic.md): active means at least one
-- completed retail order booked in the period, OR at least one
-- subscription phase overlapping the period (active as of any day
-- within it, not just active on the period's last day). A customer
-- engaged with both counts once, not twice — the grain is (period_id,
-- customer_id), deduplicated below.
with periods as (
    select * from {{ ref('accounting_periods') }}
),

order_activity as (
    select
        periods.period_id,
        orders.customer_id
    from {{ ref('fct_orders') }} as orders
    inner join periods
        on
            orders.order_date >= periods.period_start_date
            and orders.order_date <= periods.period_end_date
    where orders.order_status = 'completed'
),

subscription_activity as (
    select
        periods.period_id,
        subscriptions.customer_id
    from {{ ref('fct_subscriptions') }} as subscriptions
    inner join periods
        on
            subscriptions.phase_start_date <= periods.period_end_date
            and (
                subscriptions.phase_end_date is null
                or subscriptions.phase_end_date >= periods.period_start_date
            )
),

combined as (
    select * from order_activity
    union
    select * from subscription_activity
)

select distinct
    combined.period_id,
    combined.customer_id,
    periods.period_start_date
from combined
inner join periods on combined.period_id = periods.period_id
