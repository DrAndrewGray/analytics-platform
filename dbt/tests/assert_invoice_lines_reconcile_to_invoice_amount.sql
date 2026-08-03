-- Invoice-line reconciliation, checked in the warehouse itself — the
-- generator tests (tests/test_generate_billing_data.py) check this on
-- the raw CSVs, but staging/ingestion could in principle introduce a
-- discrepancy that a Python-only test would never see.
with line_totals as (
    select
        invoice_id,
        round(sum(line_amount)::numeric, 2) as line_total
    from {{ ref('stg_billing__invoice_lines') }}
    group by 1
)

select
    invoices.invoice_id,
    invoices.invoice_amount,
    line_totals.line_total
from {{ ref('stg_billing__invoices') }} as invoices
inner join line_totals on invoices.invoice_id = line_totals.invoice_id
where invoices.invoice_amount != line_totals.line_total
