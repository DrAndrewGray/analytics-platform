-- Row counts per accounting period, one domain's fact table at a time,
-- unioned into a single source_name/period_id/row_count shape so
-- int_volume_anomaly_by_period.sql only needs one trailing-average
-- calculation instead of three near-duplicate ones. Deliberately grain
-- = accounting period (monthly), not calendar day: see
-- docs/reliability_strategy.md for why day-grain doesn't work at this
-- dataset's volume.
with periods as (
    select * from {{ ref('accounting_periods') }}
),

orders_by_period as (
    select
        periods.period_id,
        'orders' as source_name,
        count(*) as row_count
    from {{ ref('fct_orders') }} as orders
    inner join periods
        on
            orders.order_date >= periods.period_start_date
            and orders.order_date <= periods.period_end_date
    group by periods.period_id
),

invoices_by_period as (
    select
        periods.period_id,
        'invoices' as source_name,
        count(*) as row_count
    from {{ ref('fct_invoices') }} as invoices
    inner join periods
        on
            invoices.invoice_date >= periods.period_start_date
            and invoices.invoice_date <= periods.period_end_date
    group by periods.period_id
),

events_by_period as (
    select
        periods.period_id,
        'events' as source_name,
        count(*) as row_count
    from {{ ref('fct_events') }} as events
    inner join periods
        on
            events.event_timestamp::date >= periods.period_start_date
            and events.event_timestamp::date <= periods.period_end_date
    group by periods.period_id
)

select * from orders_by_period
union all
select * from invoices_by_period
union all
select * from events_by_period
