select
    period_id,
    period_start_date,
    period_end_date,
    closed_at,
    (closed_at is not null) as is_closed
from {{ ref('accounting_periods') }}
