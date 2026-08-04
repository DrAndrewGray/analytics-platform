# Meridian Analytics Platform

An analytics engineering portfolio project: a synthetic fictional retailer
("Meridian"), ingested with Python, modeled with dbt, and tested like a
system someone's revenue reporting actually depends on.

**Phase 1** (retail: customers, orders, payments) is the foundation.
**Phase 2** extends the same warehouse with a second revenue line —
Meridian+, a subscription membership program. **Phase 3** adds
product-event analytics (browsing, identity resolution, funnels) on top
of both. Each extends the same warehouse rather than starting a new
project; see [Phase 2](#phase-2-meridian-subscriptions) and
[Phase 3](#phase-3-product-events) below. Later phases add a
finance/data-reliability lab, a semantic layer, and a benchmark-evaluated
AI copilot — each either folded in here or extracted into its own repo
once the technical story is genuinely different, not just a different
dataset with the same shape.

## Architecture

```
Retail:
  Python (Faker) --> data/raw/*.csv          --> Postgres raw schema         --> dbt
                      generate_synthetic_data.py   ingest.py

Billing (Phase 2):
  Python (Faker) --> data/raw/billing/*.csv  --> Postgres raw_billing schema --> dbt
                      generate_billing_data.py     ingest_billing.py

Events (Phase 3):
  Python (Faker) --> data/raw/events/*.csv   --> Postgres raw_events schema  --> dbt
                      generate_event_data.py       ingest_events.py
```

Three source schemas, not one: each domain is modeled as a genuinely
separate source system (see `docs/business_context.md` /
`docs/business_context_events.md`), and e.g. `raw_billing.payments` is a
different table from `raw.payments` — same name, different grain,
different source. A shared filename or schema would have silently
collided; see "Bugs this caught," below.

```
raw sources
  -> staging      (stg_*, stg_billing__*, stg_events__*)   1:1 cleaning, renaming, typing
  -> intermediate (int_*)                                  joins, grain changes, business rules
  -> marts/core, marts/billing, marts/events (dim_*, fct_*, mart_*)   dimensional model for consumption
```

## Why the model looks like this

**Two fact tables, not one.** `fct_orders` is order-grain (one row per
order) and `fct_order_items` is line-item grain (one row per product per
order). Collapsing these into a single table would force every order-level
question (revenue per day, orders per customer) to first deduplicate line
items, and every line-item question (revenue by product category) to
explode an order-grain table back out. Keeping both grains as first-class
facts avoids that back-and-forth for whoever queries this warehouse.

**Revenue vs. cash collected are tracked separately, deliberately.**
`fct_orders.order_amount` is what the order line items say the sale was
worth. `amount_collected` is what payments actually succeeded. These
diverge for real, structural reasons — refunds, failed payment attempts,
retries — and `revenue_minus_collected_variance` surfaces that gap instead
of quietly picking one number and hiding the other. This is the seam that
the finance/reconciliation extension of this platform builds on.

**Cancelled and refunded orders are kept, not filtered.** Filtering them
out in a staging or intermediate model would make that decision invisible
and unchangeable downstream. Every consumer of `fct_orders` can filter on
`order_status` themselves, explicitly.

**`int_order_payment_summary` exists as its own model** rather than being
inlined into `fct_orders`, because "how many payment attempts, did any
succeed, what was collected" is a reusable question — it'll be needed
again once a dedicated finance-reconciliation mart is added, and it's
easier to extend one aggregation model than to duplicate its logic.

## Phase 2: Meridian+ subscriptions

Full design rationale and every metric definition lives in
[`docs/business_context.md`](docs/business_context.md) and
[`docs/metric_definitions.md`](docs/metric_definitions.md) — written
*before* the models, not after. The short version:

**Subscriptions are modeled as phases, not mutable rows.** A subscription
is a sequence of continuous stretches at a fixed plan
(`fct_subscriptions`, grain = one phase). An upgrade, downgrade,
cancellation, or reactivation ends one phase and starts another. This is
the one decision everything else depends on: a single row with a mutable
`plan_id`/`status` would destroy the history needed to classify MRR
movements — an upgrade is only detectable as "MRR went up" if you can see
the before-and-after.

**MRR is contracted value, derived from subscription phases — not from
invoices or payments.** An unpaid invoice still represents contracted
MRR; a refund doesn't retroactively erase it. This is the same
recognized-value-vs-cash split as Phase 1's `fct_orders`, applied to
recurring billing (see `fct_invoices` / `mart_invoice_reconciliation` for
the cash side).

**MRR movements are computed from a gap-free month spine, not from
consecutive existing rows.** `int_subscription_chain_month_spine` gives
every subscription chain one row per calendar month from its first
activity onward, including $0 months where it wasn't active. Without
this, a `LAG()` window function would compare a reactivation's month
against whatever month the chain was *last* active — which could be many
months earlier — and misclassify reactivation as expansion.
`mart_mrr_movements` is the resulting bridge:

```
opening_mrr + new + expansion + reactivation - contraction - churned = closing_mrr
```

tested directly in `assert_mrr_bridge_reconciles.sql` against every
month in the dataset, not just spot-checked.

**Ten named scenarios, not just random data.** `scripts/generate_billing_data.py`
hand-crafts customers 1–10 (trial-to-paid conversion, upgrade, downgrade,
cancellation, reactivation, a paused-then-resumed subscription, a failed
payment retried successfully, a partial payment, a full refund, a partial
refund, an annual plan spanning a renewal, a multi-line invoice, an unpaid
invoice, a late payment) with fully deterministic dates and outcomes. The
pytest suite (`tests/test_generate_billing_data.py`) asserts on these
customers by ID — e.g. "customer 7's first payment was fully refunded" —
rather than only checking aggregate properties, which is what actually
catches a regression in the classification logic.

### Bugs this caught

Building Phase 2 surfaced three real, previously-invisible bugs in code
that had already shipped and passed CI:

1. **Every date column in the warehouse was silently stored as `text`,
   not `date`.** `pandas.read_csv()` doesn't parse dates by default, and
   `to_sql()` infers the SQL column type from whatever dtype the
   DataFrame ended up with. Comparisons and `min()`/`max()` happen to
   still work on ISO-format text (it sorts identically to the real
   date), which is exactly why this went unnoticed through all of Phase 1
   — it only surfaced once a Phase 2 model needed `date_trunc()`, which
   text doesn't support. Fixed in `scripts/ingest.py`'s
   `_coerce_date_columns()`, which also turned up a second, more subtle
   bug: pandas 3.x's `read_csv()` returns a dedicated `StringDtype`, not
   the classic `object` dtype, so an initial `dtype == "object"` check
   silently matched nothing.
2. **`DataFrame.sample()` draws from numpy's global RNG**, which the
   retail generator never seeded — only Python's `random` and Faker were.
   `order_items` generation wasn't actually deterministic despite the
   README's claim, caught by a determinism test while building the
   billing generator's own determinism test alongside it.
3. **Float summation isn't associative.** An MRR delta showed up as
   `9.999999999999998` instead of `10.00` because one branch of a `CASE`
   expression (the monthly-plan branch) returned `double precision` while
   another (the annual branch) returned `numeric` — mixing them resolved
   the whole column to `double precision`. Fixed by casting every branch
   to `numeric` explicitly, the same discipline as Phase 1's
   `Decimal`-based payment totals.

## Phase 3: product events

Full design rationale lives in
[`docs/business_context_events.md`](docs/business_context_events.md) and
[`docs/metric_definitions_events.md`](docs/metric_definitions_events.md).
The short version:

**Identity resolution is the actual point of this phase**, not funnel
math. An anonymous visitor (`anonymous_id`, a cookie-like identifier)
browses before ever signing up; once they do, every *earlier* event from
that same `anonymous_id` should resolve to their `customer_id` too —
that's what makes pre-signup browsing behavior attributable at all.
`int_identity_resolution` computes an `anonymous_id -> customer_id`
mapping, and `int_events_resolved` backfills it onto the full event
history, including events that happened before the identifying moment. A
customer can also have *multiple* `anonymous_id`s (different device,
cleared cookies) — resolution is per-`anonymous_id`, never assumed
one-to-one.

**Sessions aren't in the source data — they're computed downstream**,
same as any real pipeline would: a new session starts after a 30+ minute
gap in the same `anonymous_id`'s activity (`int_sessions`, industry-
standard threshold). This has to run on the *raw* `anonymous_id`, before
identity resolution, since sessions are about which client generated a
contiguous burst of activity, not which customer it eventually turned
out to be.

**Ten named scenarios**, in `scripts/generate_event_data.py`
(customer_ids 11-20, disjoint from Phase 2's 1-10): pre-signup browsing
that resolves correctly, a visitor who never identifies, an exact
duplicate event (double-fired beacon), a 30+ minute gap producing two
sessions, a full funnel with search, an already-identified returning
visitor, two different `anonymous_id`s resolving to one customer, an
event that arrives out of row-order but must still sort correctly by
`event_timestamp`, and a fast-vs-slow activation pair. Verified directly
against the warehouse output, not just the generator — e.g.
`assert_scenario_14_produces_two_sessions.sql` checks the actual gap
produces exactly two sessions in `fct_events`.

**`mart_funnel_conversion` is a same-day *presence* funnel, not a
sequential one — read the numbers accordingly.** A visitor who viewed
product A in the morning and bought unrelated product B that evening
still counts as completing the whole funnel that day; nothing here
confirms the view caused the cart add or the cart add caused that
specific purchase. That matches the written definition
(`docs/metric_definitions_events.md`), but "funnel" usually implies
ordered progression, so it's worth saying plainly: `view_to_purchase_rate`
means "purchased at all on a day they also viewed something," not
"viewing X caused purchasing Y." A true sequential funnel would link
specific view → cart → purchase events to each other — a real, heavier
piece of modeling deliberately deferred here.

### Bugs this caught

1. **The date-coercion fix from Phase 2 only handled plain dates
   (`%Y-%m-%d`), not timestamps.** `events.event_timestamp` has a time
   component session-gap analysis depends on entirely; the existing
   format string would have either left it as `text` or silently
   truncated away the time-of-day. `scripts/ingest.py`'s
   `_coerce_date_columns()` now tries a timestamp format first and only
   falls back to date-only, with a regression test
   (`test_ingest_events_preserves_timestamp_precision`) asserting the
   column lands as an actual `timestamp` type, not text.
2. **The retail generator's dates weren't actually pinned to the seed —
   they silently depended on which real calendar day you ran it.**
   `fake.date_between(start_date="-3y", end_date="today")` resolves
   relative strings against the real system clock at call time, not a
   fixed point. Two runs on two different days, same `SEED`, produced
   different `signup_date`/`order_date` values — which cascaded into
   different downstream billing and event data, since both are generated
   from Phase 1's customers/orders. This directly contradicted the
   project's own stated goal ("a fixed seed keeps the dataset
   reproducible"), and the existing determinism test never caught it
   because both calls in that test happen on the same day. Fixed by
   anchoring to a fixed `TODAY` constant (matching the pattern the
   billing and event generators already used), with a new test
   (`test_dates_never_exceed_the_fixed_today_anchor`) that would catch a
   relative-string regression on any day after 2026-08-02.
3. **`mart_activation` didn't require the purchase to happen after the
   signup.** `first_purchase_at` was a customer's globally-earliest
   purchase, full stop — if that purchase predated their first `signup`
   event (e.g. a guest checkout later followed by account creation), it
   would produce a negative `days_to_first_purchase` and could still
   satisfy the 14-day activation window by construction, marking someone
   activated based on activity that happened before they ever signed up.
   Confirmed this hadn't actually occurred in the current dataset (a
   direct query found zero affected customers), but the logic gap was
   real regardless of what today's synthetic data happens to contain.
   Fixed by filtering purchases to `event_timestamp >= first_signup_at`
   before taking the minimum, with both a `not_negative` test on
   `days_to_first_purchase` and a dedicated singular test
   (`assert_activation_purchase_not_before_signup.sql`).

## What's tested, and why

- **Referential integrity** (`relationships` tests) between orders,
  customers, products, and payments — the joins in `int_*` and `fct_*`
  models are only trustworthy if these hold.
- **`accepted_values`** on `order_status` and `payment_status` — these
  drive conditional logic upstream (e.g. revenue recognition), so an
  unexpected new status value should fail loudly, not silently fall
  through a `case` statement.
- **A custom generic test (`not_negative`)** on `order_amount` and
  `amount_collected` — a negative value in either would indicate a bug in
  the aggregation logic, not real business data.
- **A singular test** (`assert_no_negative_total_revenue`) checking a
  table-level invariant (total completed-order revenue can't be negative)
  rather than a per-row condition — demonstrates that not everything worth
  testing fits the generic-test, per-column shape.
- **Source freshness** on every raw table across all three domains, based
  on a genuine `_loaded_at` ingestion timestamp set by `scripts/ingest.py`
  — not on business dates like `order_date`. Freshness should answer "how long
  since this actually arrived through the pipeline," which a business
  date can't tell you (an order placed a year ago that loaded five
  minutes ago is fresh; using `order_date` for that check would say the
  opposite).
- **A snapshot** (`customers_snapshot`) using the `check` strategy on
  `region` and `email`, to demonstrate SCD Type 2 history capture even
  though the synthetic source is currently static between manual
  regenerations.
- **`assert_mrr_bridge_reconciles.sql`** — the MRR bridge holds exactly
  for every month, checked in the warehouse, not just implied by
  `mart_mrr_movements` existing.
- **`assert_invoice_lines_reconcile_to_invoice_amount.sql`** — the same
  invariant `tests/test_generate_billing_data.py` checks on the raw CSVs,
  checked again in the warehouse itself, since staging/ingestion could in
  principle introduce a discrepancy a Python-only test would never see.
- **`assert_subscription_phases_do_not_overlap.sql`** — within a chain,
  one phase's end can't fall after the next phase's start (beyond the
  single allowed same-month transition), or MRR movement classification
  would be ambiguous.
- **`assert_annual_plans_normalize_to_monthly_mrr.sql`** — annual-plan
  MRR equals `list_price / 12`, checked directly rather than trusted.
- **`assert_anonymous_id_maps_to_at_most_one_customer.sql`** —
  `int_identity_resolution` uses `max(customer_id)` per `anonymous_id`,
  which is only correct if that assumption holds; checked directly
  rather than trusted.
- **`assert_no_duplicate_events_remain.sql`** — structural check that
  deduplication actually happened, not just that the logic exists.
- **`assert_scenario_14_produces_two_sessions.sql`** — a named-scenario
  test: the 2-hour gap in the test data must produce exactly two
  sessions, checked against the real warehouse output.
- **`assert_activation_purchase_not_before_signup.sql`** — a customer's
  first counted purchase can never predate their first signup; guards
  against the exact bug described above.

## Running it locally

Requires Docker Desktop running, and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Install Python dependencies
uv sync

# 2. Start Postgres
docker compose up -d
docker compose ps   # wait for "healthy"

# 3. Generate synthetic data and load it into the raw schemas
# (billing and events both need customers.csv, so generate retail first;
# events also needs products.csv and orders.csv)
uv run python scripts/generate_synthetic_data.py    # retail: data/raw/*.csv
uv run python scripts/generate_billing_data.py       # billing: data/raw/billing/*.csv
uv run python scripts/generate_event_data.py         # events: data/raw/events/*.csv
uv run python scripts/ingest.py                      # -> raw schema
uv run python scripts/ingest_billing.py              # -> raw_billing schema
uv run python scripts/ingest_events.py               # -> raw_events schema

# 4. Run the Python test suite (generator + ingestion tests)
uv run pytest

# 5. Install dbt packages and build the warehouse
cd dbt
uv run dbt deps --profiles-dir .
uv run dbt build --profiles-dir .

# 6. Explore the docs
uv run dbt docs generate --profiles-dir .
uv run dbt docs serve --profiles-dir .
```

`dbt build` runs models, tests, and snapshots together, in dependency
order — if a test on `stg_orders` fails, downstream marts that depend on
it are skipped rather than built on top of bad data.

## Tooling

- **ruff** — Python linting/formatting (`uv run ruff check .`)
- **sqlfluff** — SQL linting for the dbt models and singular tests
  (`uv run sqlfluff lint dbt/models dbt/tests`)
- **pyright** — Python type checking (`uv run pyright scripts tests`)
- **pytest** — generator and ingestion tests across all three domains
  (`uv run pytest`). The ingestion tests need a reachable Postgres and
  skip themselves otherwise. They run against isolated `raw_test` /
  `raw_billing_test` / `raw_events_test` schemas, not the real `raw` /
  `raw_billing` / `raw_events` schemas dbt builds from — several of these
  tests are deliberately destructive (dropping tables/columns to simulate
  failure scenarios), and running destructive operations against shared
  dev state as a side effect of `pytest` would be its own bug. One test
  is a regression test for a real bug: re-ingesting used to `DROP TABLE`,
  which Postgres refuses once a dbt view depends on it — ingestion now
  truncates instead, and the test recreates that exact scenario to guard
  against it coming back.

## Environments

`dbt/profiles.yml` defines two targets against the same Postgres:
`dev` (schema `analytics`, for local work) and `ci` (schema
`analytics_ci`, used by GitHub Actions). They're kept schema-isolated
rather than sharing one, so a CI run can never leave behind state that
affects local development, or vice versa. Snapshots get the same
treatment (`analytics_snapshots` / `analytics_ci_snapshots`) — a
`target_schema` hardcoded to a single literal name would have quietly
defeated this isolation for snapshots specifically.

## CI

GitHub Actions spins up a real Postgres service container, regenerates
the retail, billing, and event synthetic data fresh (so source freshness
checks always pass), runs the Python test suite, then runs `dbt build`
against the `ci` target on every push — the warehouse either builds and
passes its tests, or the check fails. See `.github/workflows/ci.yml`.

## Roadmap

Phase 1 (retail), Phase 2 (Meridian+ subscriptions), and Phase 3
(product events) are all done. Next up, per the original plan: a
finance/data-reliability lab, a semantic layer, and a benchmark-evaluated
AI copilot — extracted into their own repos once each has a technical
story genuinely different from what's here, not just a different dataset
with the same shape.

[`docs/roadmap/phase_2_subscription_spec.md`](docs/roadmap/phase_2_subscription_spec.md)
is kept as a historical record of the original Phase 2 spec — the actual
implementation follows it closely, with the specific deviations called
out in [Phase 2: Meridian+ subscriptions](#phase-2-meridian-subscriptions), above.
