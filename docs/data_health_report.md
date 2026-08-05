# Data health report

Generated 2026-08-05 15:56 UTC by `scripts/generate_health_report.py`. This is a point-in-time snapshot, not a live dashboard — regenerate after any `dbt build` / `dbt source freshness` run. See docs/reliability_strategy.md for why this is a file, not a service.

## Tests

- **pass**: 196

## Source freshness

12 sources checked, 0 not passing.

## Contracted models

- fct_invoices
- fct_orders
- mart_cash_movements_by_period
- mart_revenue_reconciliation_by_period

## Volume anomalies

None.

## Open late period-close adjustments

- refund_id=1: booked in period 25, landed in period 26 (10 days after close)

