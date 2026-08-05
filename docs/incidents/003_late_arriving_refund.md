# Incident 003: a refund lands against a closed period

**Category**: late-arriving data changes a closed-period result
**Severity**: informational (correct, expected behavior — not a bug)
**Status**: resolved (injected and recovered as a controlled demo)

## Summary

A new billing refund landed today against an invoice whose accounting
period closed almost a month ago. `dbt build` stayed fully green —
this is not a test failure, and building a test that made it one would
contradict Phase 4's own design (`docs/metric_definitions_finance.md`
is explicit that a late refund is normal, tracked activity, not an
error). What changed instead: `mart_revenue_reconciliation_by_period`'s
number for that already-closed period is no longer what it was, and
`scripts/generate_alert_report.py`'s informational section is what
actually surfaces that — the one incident in this set where the
"control" is an alert, not a red test.

## Failure injected

```
uv run python scripts/inject_failure.py late-arriving-refund
```

Found the most recent invoice with a fully-paid, unrefunded payment
against an already-closed accounting period, and inserted a new refund
against it dated today:

- Invoice 169 (customer 112), booked 2026-06-28 — period 42
  (2026-06-01 to 2026-06-30), closed 2026-07-10.
- New refund 3, $9.99, dated 2026-08-05 — 26 days after period 42
  closed.

## Detection

```
$ dbt build --profiles-dir .
...
Finished running 1 exposure, 2 seeds, 1 snapshot, 24 table models, 196 data tests, 32 view models
Completed successfully
Done. PASS=255 WARN=0 ERROR=0 SKIP=0 NO-OP=1 REUSED=0 TOTAL=256
```

Nothing red. That's correct, not a gap — the actual detection surface
is the informational section of the alert report:

```
$ uv run python scripts/generate_alert_report.py
OK: no failures in the most recent dbt run.

INFO: 2 open late period-close adjustment(s) (not a failure):
  - refund_id=3: booked in period 42, landed in period 44 (26 days after close)
  - refund_id=1: booked in period 25, landed in period 26 (10 days after close)
```

`refund_id=1` is the named scenario from Phase 4 (customer 7); `refund_id=3`
is this incident. Both come from the same query
(`fct_period_close_adjustments.is_late_adjustment`), so this section
would grow by one every time a genuinely new late adjustment shows up —
which is exactly the "did anything change since I last looked" question
an alert should answer, without needing a persisted "since last run"
state file: the mart itself already carries every adjustment that's
ever happened, and the whole list is small enough to just re-show in
full each time.

## Impact (identified directly, not via lineage)

Unlike Incidents 001–002, there's no DAG breakage to trace — the
"impact" here is a specific number changing under an already-reported
period, which is a business question, not a dependency-graph one:

```sql
select period_id, is_closed, billing_net_booked_revenue,
       billing_refunded_amount_against_bookings
from analytics_marts.mart_revenue_reconciliation_by_period
where period_id = 42;
```
```
 period_id | is_closed | billing_net_booked_revenue | billing_refunded_amount_against_bookings
-----------+-----------+----------------------------+------------------------------------------
        42 | t         |                    1808.80 |                                     9.99
```

Period 42 is `is_closed = true` — reported, final, presumably already
used in a month-end close — and its `billing_refunded_amount_against_bookings`
is no longer zero. Anyone who screenshotted this mart before today and
compares it against a fresh query now gets a different number for a
period they had every reason to believe was settled.

## Root cause

Not a bug: a customer requested (or was issued) a refund against a
subscription invoice more than three weeks after that invoice's period
closed. Real businesses see this constantly — chargebacks, delayed
customer-service resolutions, retroactive adjustments — and Phase 4 was
built specifically to model it as first-class, trackable activity
(`fct_period_close_adjustments`, `is_late_adjustment`), not an
exception path.

## Response

No fix needed — the system did what it should. The only action item is
making sure whoever consumes `mart_revenue_reconciliation_by_period` for
a closed period *knows* it can still move, which is a communication
problem, not an engineering one: this is exactly what the alert's
informational section and `docs/runbook.md`'s late-adjustment section
are for.

## Recovery verification

"Recovery" here just means returning to the pre-injection dataset, not
fixing anything broken:

```
$ uv run python scripts/generate_synthetic_data.py
$ uv run python scripts/generate_billing_data.py
$ uv run python scripts/generate_event_data.py
$ uv run python scripts/ingest.py && uv run python scripts/ingest_billing.py && uv run python scripts/ingest_events.py
$ dbt build --profiles-dir .
Done. PASS=255 WARN=0 ERROR=0 SKIP=0 NO-OP=1 REUSED=0 TOTAL=256
$ uv run python scripts/generate_alert_report.py
INFO: 1 open late period-close adjustment(s) (not a failure):
  - refund_id=1: booked in period 25, landed in period 26 (10 days after close)
```

Back to exactly the pre-injection state (the original customer-7
scenario, refund_id=1, still present as expected).

## Follow-up / lessons

- **Not every control this phase built is a pass/fail test, and that's
  deliberate.** Incidents 001 and 002 are "the build goes red, fix it."
  This one is "the build stays green, and something still needs a
  human to look at it" — a different, equally real category of
  reliability concern that a test-only strategy would have no way to
  represent at all.
- **A mart that includes `is_closed` on every row is what makes this
  detectable without extra machinery.** Nothing about
  `mart_revenue_reconciliation_by_period`'s schema had to change for
  this incident to be catchable — Phase 4's own modeling decision (keep
  `is_closed` on the reconciliation mart, not just the periods table)
  is what makes "did a closed period move" an answerable question at
  all.
