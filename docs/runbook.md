# Runbook: diagnosing and recovering from a failed `dbt build`

This is the short, practical companion to `docs/reliability_strategy.md`
(the design rationale) and `docs/incidents/` (worked examples). Start
here when something's actually broken.

## 1. Read the alert, not just the log

```
uv run python scripts/generate_alert_report.py
```

Run this right after any failed `dbt build` (from the repo root, not
`dbt/`). It reads `dbt/target/run_results.json` and
`dbt/target/manifest.json` and reports, for every failure: what broke,
the error message, and everything downstream of it — models, tests,
exposures — computed from the same dependency graph dbt itself builds
from. That last part is the point: don't manually guess what's affected
by scrolling `dbt build`'s log. It also always prints an informational
section for any open late period-close adjustments — not a failure,
just worth knowing about (see `docs/incidents/003_late_arriving_refund.md`).

If you need the raw structured data (e.g. to paste into an incident
doc): `--json`, or `--output some_file.json` to write it out.

## 2. Ask "what else does this touch" before you start fixing

```
uv run python scripts/impact_analysis.py <model_name>
uv run python scripts/impact_analysis.py <schema.table>   # a raw source
```

Same dependency graph as the alert script, queryable directly for any
model or source — useful before you've even run `dbt build`, e.g. if
someone tells you a source system is about to change and you want to
know the blast radius in advance.

## 3. Classify the failure

| Symptom | Likely cause | Where to look |
|---|---|---|
| `column "x" does not exist` at a staging model | A source column was dropped or renamed | `docs/incidents/001_dropped_source_column.md` |
| `operator does not exist: text = bigint` (or similar) on a test | A source column changed type | `docs/incidents/002_column_type_change.md` |
| `This model has an enforced contract that failed` | A contracted mart's actual output no longer matches its declared columns — often a type change flowing through from staging | `docs/data_contracts.md`, Incident 002 |
| `accepted_values` test fails | An unexpected value showed up in a status-like column | — |
| `unique` test fails, or a contracted model's `dbt build` fails with a primary-key violation | Duplicate rows for what should be a unique key | — |
| `relationships` test fails | A foreign key doesn't resolve — orphaned row, or (see above) a type mismatch | — |
| `assert_no_volume_anomaly` fails | A source's row count for a closed period dropped >=40% vs. its trailing average | `docs/reliability_strategy.md` (threshold rationale) |
| `not_implausibly_large` fails | A single order/invoice amount exceeds its calibrated ceiling | `docs/reliability_strategy.md` |
| `dbt source freshness` reports `error` | A source hasn't loaded within its `error_after` window | — |
| Alert script's informational section grows | A refund landed against an already-closed period | `docs/incidents/003_late_arriving_refund.md` — usually not a bug |
| `scripts/check_source_schema.py` reports drift | A raw table's structure changed | `docs/data_contracts.md` |

## 4. Recover

**For a data-only problem** (bad values, not a structural change):
regenerate synthetic data and re-run ingestion, then rebuild.

```
uv run python scripts/generate_synthetic_data.py
uv run python scripts/generate_billing_data.py
uv run python scripts/generate_event_data.py
uv run python scripts/ingest.py
uv run python scripts/ingest_billing.py
uv run python scripts/ingest_events.py
cd dbt && uv run dbt build --profiles-dir .
```

**For a schema-shaped problem** (a column was dropped or changed type —
Incidents 001 and 002 both hit this): the step above usually isn't
enough. `scripts/ingest.py` truncates and re-inserts into the *existing*
table by design, which assumes the table's structure is still correct —
true for a normal data refresh, false here. Drop the affected raw
table(s) first, with `CASCADE` (don't assume a plain `DROP TABLE` will
work — see Incident 002's "Response" for why a dbt build run in between
injecting and recovering can recreate the exact view that was blocking
it):

```
psql -c "DROP TABLE raw.<table> CASCADE;"
uv run python scripts/ingest.py   # (or ingest_billing.py / ingest_events.py)
cd dbt && uv run dbt build --profiles-dir .
```

**For a late-closed-period adjustment**: there's usually nothing to
recover — it's expected behavior, not a fault. Confirm the number is
sane (Incident 003), and make sure whoever consumes
`mart_revenue_reconciliation_by_period` for that period knows it moved.

**For a stale source**: find out why the real ingestion step for that
source stopped running (this only happens in the demo via
`scripts/inject_failure.py source-stale`, which just backdates
`_loaded_at` directly) — in the synthetic version of this project,
re-running the matching `ingest*.py` script resets it.

## 5. Verify recovery, both targets

```
cd dbt
uv run dbt build --profiles-dir .              # dev
uv run dbt build --profiles-dir . --target ci  # ci
uv run dbt source freshness --profiles-dir .
uv run dbt source freshness --profiles-dir . --target ci
```

Both need to come back clean — `raw` schemas are shared across `dev`
and `ci` (see `docs/reliability_strategy.md`), so a raw-schema-level
failure (a dropped column, a type change) breaks both at once, and
recovery isn't done until both rebuild.

## 6. Regenerate the health snapshot

```
uv run python scripts/generate_health_report.py
```

Writes `docs/data_health_report.md` — a point-in-time summary of test
results, freshness, contracted models, volume anomalies, and open late
adjustments. Not a live dashboard (see `docs/reliability_strategy.md`
for why); regenerate it after any build worth recording.

## Practicing this without breaking anything real

```
uv run python scripts/inject_failure.py list
uv run python scripts/inject_failure.py <scenario>
```

Every scenario runs real DDL/DML against the actual database, then
walks through steps 1–5 above for real. See `docs/incidents/` for three
fully worked examples, output included.
