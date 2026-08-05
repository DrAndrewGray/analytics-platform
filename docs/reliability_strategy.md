# Reliability strategy — Phase 5

Phases 1–4 built a warehouse that's *correct* under normal conditions.
Phase 5 asks a different question: what happens when a source changes
shape, a pipeline silently stops loading, or a number moves outside its
plausible range — and how would anyone actually find out? This phase
adds a small reliability lab around the existing Meridian platform, not
a new revenue domain.

## Scope

This is deliberately a lab, not a product. It does not attempt to
rebuild Monte Carlo, ship a UI, or run continuously in the background.
Every control here is either a dbt test/contract that runs as part of
`dbt build` (so it's exercised on every CI run, for free, using
infrastructure Phases 1–4 already pay for), or a small Python script
invoked on demand. The portfolio claim is narrow and specific:

> I understand how analytics systems fail, how to detect failures
> early, and how to communicate their impact — not "I can operate a
> monitoring SaaS."

## The eight controls, and where each one lives

| Control | Mechanism | Where |
|---|---|---|
| Source & model contracts | dbt `contracts: enforced` on selected marts; a checked-in expected-schema snapshot + diff script for raw sources (dbt has no source-level contract primitive — see `docs/data_contracts.md`) | `dbt/models/marts/**/*.yml`, `scripts/check_source_schema.py` |
| Freshness monitoring | `dbt source freshness` (already built in Phases 1–3, all 12 sources) | `dbt/models/staging/_staging__*sources.yml` |
| Row-volume anomaly detection | Period-grain trailing-average comparison, singular tests | `dbt/models/intermediate/int_volume_by_period_*.sql`, `dbt/tests/assert_no_volume_anomaly_*.sql` |
| Schema-change detection | dbt contracts (model level) + `scripts/check_source_schema.py` (source level) | see above |
| Metric anomaly detection | Bounded-range singular tests on marts already built in Phase 4 | `dbt/tests/assert_no_revenue_anomaly_*.sql` |
| Lineage & impact analysis | `manifest.json` parsed to answer "if model X breaks, what's downstream" | `scripts/impact_analysis.py` |
| Alerts | `run_results.json` + `manifest.json` parsed into one structured alert (console + JSON) after every `dbt build` | `scripts/generate_alert_report.py` |
| Incident investigation & documentation | Fixed template, three worked incidents | `docs/incidents/*.md` |

## Why period-grain, not day-grain, for volume anomalies

Meridian's synthetic dataset is small — a few hundred orders and well
under a thousand events across two-plus years. Day-level order/event
counts range from 0 to the high teens; a day-over-day percentage
comparison at that scale is almost pure noise (going from 2 events to 6
is "+200%" and means nothing). Real production volume monitoring
usually has enough daily traffic for day-grain comparisons to be
meaningful; this dataset doesn't, and pretending otherwise would produce
a check that's either constantly false-alarming or tuned so loose it
never fires. Volume anomaly detection here instead uses the same
monthly `accounting_periods` grain Phase 4 already established —
enough rows per bucket for a percentage comparison to mean something,
and it reuses infrastructure that already exists rather than inventing
a second period concept.

## Why only closed periods are eligible for volume/metric anomaly checks

The current and most recent accounting periods are still accumulating
data by construction (`dim_accounting_periods.is_closed = false` for
the last two periods, per Phase 4). Comparing an in-progress period's
partial count against a prior period's complete count always looks like
a cliff and would false-alarm on every single CI run. Anomaly checks
here are scoped to `is_closed = true` periods only — reusing Phase 4's
own definition of "final" rather than inventing a second one.

## Why thresholds are calibrated from this dataset's own history, not picked arbitrarily

Every threshold below (volume-drop %, revenue-spike bound) was set by
querying this dataset's actual month-over-month variance first, then
picking a threshold wide enough to not fire on any real month in the
current warehouse but tight enough to fire on the injected failure
scenarios in `docs/incidents/`. See each test's header comment for the
specific numbers behind its threshold — same discipline the project
already applies to business logic (e.g. the 30-minute session-gap
threshold in Phase 3), applied to reliability thresholds too.

- **Volume drop**: -40%, eligible only for closed periods with a
  3-period trailing average of at least 10 rows. The worst real
  month-over-month drop on record at that scale is -19.1% (orders,
  Feb 2025) — more than 2x margin below the threshold.
- **`order_amount` ceiling**: $10,000. Grounded in the actual product
  catalog, not a round guess: the most expensive product is $293.09,
  the largest quantity ever ordered in one order is 12 units — a
  generous 20-unit purchase of the priciest product tops out around
  $5,861, and $10,000 sits comfortably above that with room for catalog
  growth, while still being ~4x the current real maximum order
  ($2,542.65).
- **`invoice_amount` ceiling**: $2,000. The most expensive plan is
  $199/month; $2,000 is ~10x that, generous margin for multi-line or
  proration edge cases.

**Deliberately not built: period-over-period revenue-trend anomaly
detection**, the metric-level equivalent of the volume check above.
Tried it first, then dropped it: month-over-month revenue swings during
this dataset's early growth are enormous and entirely legitimate — e.g.
+616% (period 9 vs. 8) and +172% (period 13 vs. 12), reflecting a
business genuinely starting from near-zero, not a data problem. Getting
a trailing-average threshold wide enough to tolerate that would have to
be so loose it couldn't catch a real anomaly either — a check that
can't fail is worse than no check, since it creates false confidence.
The row-level `order_amount`/`invoice_amount` ceilings above catch the
concrete "revenue jumps beyond a plausible range" scenario this phase
actually needs to demonstrate (one implausible transaction) without
pretending a noisy, immature time series can support trend detection it
can't.

## Failure injection

`scripts/inject_failure.py` is a CLI with one subcommand per failure
scenario (`drop-column`, `change-column-type`, `bad-status`,
`duplicate-pk`, `broken-fk`, `volume-drop`, `revenue-spike`,
`source-stale`, `late-arriving-refund`). Each subcommand runs real DDL/
DML directly against the target Postgres schemas — no separate "fake
broken" environment, because the whole point is demonstrating what the
*actual* pipeline does when its actual inputs break. Recovery, in every
case, is the same well-tested path the project already uses whenever
data needs to be reset: regenerate the synthetic data and re-run
ingestion (`scripts/generate_*.py` + `scripts/ingest*.py`), then
`dbt build` again. Real incident recovery is usually "restore from a
known-good source," not a bespoke undo button per failure type, and
reusing the existing reset path means recovery here is exercised by the
same regression tests as every other phase, not a new one-off after
this doc is written.

## What's explicitly out of scope

- No continuously-running monitoring process. Every check here runs as
  part of `dbt build`/`dbt test`/`dbt source freshness`, or on demand
  via a script — the same model CI already uses.
- No UI. The "dashboard" deliverable is a generated Markdown report
  (`docs/data_health_report.md`, regenerated by
  `scripts/generate_health_report.py`), checked into the repo like
  everything else, not a hosted app.
- No alerting integration (Slack/PagerDuty/email). The alert script
  produces structured output (console + JSON); wiring that to a real
  paging system is a config problem, not a modeling one, and out of
  scope for a portfolio piece about analytics reliability specifically.
- No attempt to cover all nine injector scenarios with a fully worked
  incident. The injector supports a broad set (breadth), but
  `docs/incidents/` documents three in depth (depth) — chosen to span
  three genuinely different detection mechanisms, not just three
  different failures: a required column disappearing (a plain
  compilation error, caught one layer downstream), a column silently
  changing type (caught by two independent controls at two different
  points — a generic `relationships` test and a dbt contract), and
  late-arriving data changing a closed period's own report (no test
  failure at all, by design — caught only by the alert script's
  informational section). The third case connects directly to Phase 4's
  period-close modeling.
