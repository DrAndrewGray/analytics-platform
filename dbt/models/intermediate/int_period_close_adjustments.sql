-- Every billing refund, annotated with the period its original invoice
-- belonged to, the period the refund itself lands in, and whether the
-- original period was already closed by the time the refund happened
-- (docs/metric_definitions_finance.md). Not filtered to late adjustments
-- only — that's a consumer choice (is_late_adjustment), same reasoning
-- as fct_orders keeping cancelled/refunded rows instead of filtering
-- them upstream.
with refunds as (
    select * from {{ ref('stg_billing__refunds') }}
),

payments as (
    select * from {{ ref('stg_billing__payments') }}
),

invoices as (
    select * from {{ ref('stg_billing__invoices') }}
),

periods as (
    select * from {{ ref('accounting_periods') }}
),

refund_context as (
    select
        refunds.refund_id,
        refunds.refund_date,
        refunds.refund_amount,
        payments.invoice_id,
        invoices.invoice_date
    from refunds
    inner join payments on refunds.payment_id = payments.payment_id
    inner join invoices on payments.invoice_id = invoices.invoice_id
),

with_periods as (
    select
        refund_context.refund_id,
        refund_context.invoice_id,
        refund_context.invoice_date,
        refund_context.refund_date,
        refund_context.refund_amount,
        original_period.period_id as original_period_id,
        original_period.closed_at as original_period_closed_at,
        adjustment_period.period_id as adjustment_period_id
    from refund_context
    inner join periods as original_period
        on
            refund_context.invoice_date >= original_period.period_start_date
            and refund_context.invoice_date <= original_period.period_end_date
    inner join periods as adjustment_period
        on
            refund_context.refund_date >= adjustment_period.period_start_date
            and refund_context.refund_date <= adjustment_period.period_end_date
)

select
    refund_id,
    invoice_id,
    invoice_date,
    refund_date,
    refund_amount,
    original_period_id,
    adjustment_period_id,
    original_period_closed_at,
    (
        original_period_closed_at is not null and refund_date > original_period_closed_at
    ) as is_late_adjustment,
    -- Both operands are `date`, so this subtraction is already an
    -- integer day count in Postgres — no extract(epoch from ...)
    -- needed (that's only meaningful for interval/timestamp values).
    case
        when original_period_closed_at is not null and refund_date > original_period_closed_at
            then refund_date - original_period_closed_at
    end as days_after_close
from with_periods
