# Meridian Analytics Platform

An analytics engineering portfolio project: a synthetic fictional retailer
("Meridian"), ingested with Python, modeled with dbt, and tested like a
system someone's revenue reporting actually depends on.

This is the foundation layer of a larger, progressively-extended analytics
platform. Later phases add subscription/revenue modeling, product-event
analytics, finance reconciliation, a data-reliability lab, a semantic
layer, and a benchmark-evaluated AI copilot — each either folded into this
warehouse or extracted into its own repo when the technical story is
genuinely different, not just a different dataset with the same shape.

## Architecture

```
Python (Faker) --> data/raw/*.csv --> Postgres raw schema --> dbt --> analytics schema
                    scripts/generate_synthetic_data.py       scripts/ingest.py
```

```
raw sources
  -> staging      (stg_*)            1:1 cleaning, renaming, typing
  -> intermediate (int_*)            joins and grain changes
  -> marts/core   (dim_*, fct_*)     dimensional model for consumption
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
- **Source freshness** on `orders`, `payments`, and `customers` — flags
  when the "extract" has gone stale, which matters more once this stops
  being synthetic data regenerated on demand.
- **A snapshot** (`customers_snapshot`) using the `check` strategy on
  `region` and `email`, to demonstrate SCD Type 2 history capture even
  though the synthetic source is currently static between manual
  regenerations.

## Running it locally

Requires Docker Desktop running, and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Install Python dependencies
uv sync

# 2. Start Postgres
docker compose up -d
docker compose ps   # wait for "healthy"

# 3. Generate synthetic data and load it into the raw schema
uv run python scripts/generate_synthetic_data.py
uv run python scripts/ingest.py

# 4. Install dbt packages and build the warehouse
cd dbt
uv run dbt deps --profiles-dir .
uv run dbt build --profiles-dir .

# 5. Explore the docs
uv run dbt docs generate --profiles-dir .
uv run dbt docs serve --profiles-dir .
```

`dbt build` runs models, tests, and snapshots together, in dependency
order — if a test on `stg_orders` fails, downstream marts that depend on
it are skipped rather than built on top of bad data.

## Tooling

- **ruff** — Python linting/formatting (`uv run ruff check .`)
- **sqlfluff** — SQL linting for the dbt models (`uv run sqlfluff lint dbt/models`)
- **pyright** — Python type checking (`uv run pyright scripts`)

## CI

GitHub Actions spins up a real Postgres service container, regenerates
the synthetic data fresh (so source freshness checks always pass), and
runs `dbt build` on every push — the warehouse either builds and passes
its tests, or the check fails. See `.github/workflows/ci.yml`.
