# Phase 2 spec: subscription billing extension

**Status: deferred, not Phase 1 work.** This document lays out the
requirements for extending the warehouse with a subscription-billing
domain (plans, subscriptions, invoices, payments, refunds, MRR/NRR-style
metrics) — Phase 2 in this project's roadmap.

It was originally drafted assuming the *retail* warehouse in this repo
(customers/products/orders/order_items/payments) was an incomplete
attempt at a subscription business, and that Project 1 needed to be
rewritten to match. That assumption was wrong: the retail warehouse is
the intentional, deliberately-scoped Phase 1 foundation, and subscription
modeling was always planned as a Phase 2 extension of the same
warehouse — not a replacement for it. The retail models, generator, and
dimensional structure stay as-is.

What follows is kept as the working spec for that Phase 2 work, since the
domain modeling, source-contract, and test-design thinking in it is
sound — it's just scoped to the wrong phase in its original form.

---

Assuming we realign Project 1 with the subscription-company design brief, the current repository is a useful scaffold but needs substantial domain remodeling.

## What can be retained

These foundations are already present and reusable:

- Docker Compose with PostgreSQL 16
- `uv` dependency management
- Python ingestion-script structure
- Deterministic Faker-based generation
- dbt staging/intermediate/mart organization
- A snapshot example
- Generic and singular dbt-test patterns
- Ruff, Pyright, SQLFluff, and GitHub Actions
- Source freshness, exposures, and dbt documentation structure
- The general revenue-versus-cash reconciliation idea

The retail-specific generator and dbt models should either be replaced or preserved on a separate branch/tag as an earlier prototype.

# 1. Resolve the scope and project boundaries

Before rewriting code, document the distinction between Projects 1 and 2:

- **Project 1:** Core subscription billing warehouse, dimensional modeling, tests, documentation, and a small dashboard.
- **Project 2:** Advanced SaaS metrics such as MRR movements, NRR, GRR, retention cohorts, churn analysis, and CLV.

Project 1 still needs enough subscription logic to establish the warehouse:

- Active subscriptions and customers
- Monthly and annual plans
- Issued invoices
- Successful, failed, and partial payments
- Refunds
- Basic normalized recurring revenue
- Revenue-versus-cash reconciliation

This prevents the two projects from becoming duplicate dbt warehouses.

# 2. Write the pre-code design documents

Create:

- `docs/business_context.md`
- `docs/metric_definitions.md`
- `docs/source_contracts.md`
- `docs/model_design.md`
- `docs/acceptance_criteria.md`

They should establish the following.

### Business context

Define:

- What Meridian sells
- Whether customers are individuals, organizations, or both
- Available plans
- Monthly and annual billing behavior
- Trial rules
- Supported countries and currencies
- Invoice and payment behavior
- Refund policy
- Reporting stakeholders and their needs

### Business questions

Select approximately eight questions, such as:

- How many active customers and subscriptions exist?
- How much normalized recurring revenue exists?
- Which plans produce the most revenue?
- How many subscriptions started or ended each month?
- How much invoiced value has been collected?
- Which invoices remain unpaid or partially paid?
- How much has been refunded?
- How do customers and revenue vary by country?

### Metric definitions

Define precise rules for at least:

- Active customer
- Active subscription
- MRR
- New MRR
- Collected revenue
- Invoiced revenue
- Outstanding invoice value
- Refunded amount

Resolve:

- End-of-period cancellation
- Paused subscriptions
- Trials
- Annual-plan normalization
- Taxes
- Partial payments
- Refund dates
- Failed payment retries
- Currency conversion
- Reactivations

### Model grains

Every planned model needs a one-sentence grain declaration. For example:

> `fct_invoices` contains one row per issued invoice.

# 3. Replace the retail source model

The current sources are:

- Customers
- Products
- Orders
- Order items
- Payments

The intended sources should be divided into realistic systems.

### CRM source

Add:

- `customers`
- `organizations`

Include customer acquisition date, country, organization membership, and mutable customer attributes.

### Billing source

Add:

- `plans`
- `subscriptions`
- `invoices`
- `invoice_lines`
- `payments`
- `refunds`

Optional for the first version:

- `exchange_rates`

Each source contract needs:

- Primary key
- Row grain
- Foreign keys
- Business timestamps
- Ingestion timestamp
- Mutable fields
- Nullable fields
- Expected statuses
- Known quality problems

# 4. Rebuild the synthetic-data generator

The existing generator creates customers, products, orders, order items, and one payment per order. It needs subscription lifecycle generation.

Add deterministic generation for:

- Monthly and annual plans
- Trials
- Subscription starts and renewals
- Cancellations at period end
- Immediate cancellations if supported
- Upgrades and downgrades
- Pauses
- Reactivations
- Multiple subscriptions per customer
- Invoice generation per billing period
- Multiple invoice lines
- Successful payments
- Failed and retried payments
- Partial payments
- Full and partial refunds
- Late-arriving records
- Mutable customer attributes
- Multiple countries
- Multiple currencies, if retained in Part 1

Add explicitly controlled edge-case scenarios rather than relying entirely on random probabilities. For example:

- One annual subscription with a mid-period upgrade
- One partially paid invoice
- One payment retried successfully
- One partial refund
- One customer reactivated after cancellation
- One late-arriving payment
- One duplicate CRM customer
- One invoice updated after ingestion

Known scenarios should have predictable expected results for tests.

# 5. Improve raw ingestion

The current ingestion is a simple truncate-and-reload loop. That is acceptable for the first vertical slice, but it still needs:

- CRM and billing source separation
- Configuration for all new source tables
- Schema or column validation before loading
- Clear errors for malformed inputs
- Consistent timestamp handling
- Ingestion metadata such as `_loaded_at`
- Deterministic table-loading order
- Basic logging
- Idempotency verification
- Python tests

Source freshness must use actual ingestion timestamps. The current configuration uses business fields such as `signup_date` and `order_date`, which do not reliably measure pipeline freshness.

> **Note (Phase 1, already done):** the retail warehouse now has a real
> `_loaded_at` ingestion timestamp and source freshness is based on it,
> not on business dates. Carry this same pattern into the billing
> sources in Phase 2.

Do not turn this into the reusable ingestion framework yet; pagination, API retries, backfills, and multi-destination support belong mainly to Project 6.

# 6. Add Python testing

`pytest` is not currently configured.

Add tests for:

- Reproducible output from the fixed seed
- Referential integrity in generated data
- Invoice totals equal their line items
- Annual and monthly billing dates
- Payment and refund constraints
- Controlled edge-case scenarios
- Missing-file behavior
- Repeatable ingestion
- Schema validation
- Invalid status handling

Add `pytest` to the development dependencies and CI.

> **Note (Phase 1, already done):** pytest is configured, with generator
> tests (determinism, referential integrity, payment/order-total
> reconciliation using `Decimal` rather than float summation) and
> ingestion tests (idempotency, and a specific regression test for a real
> bug where re-ingesting broke once dbt views depended on the raw
> tables). Extend this same suite with billing-domain cases in Phase 2
> rather than starting a second test setup.

# 7. Replace the dbt staging layer

Replace the retail staging models with source-qualified models:

- `stg_crm__customers`
- `stg_crm__organizations`
- `stg_billing__plans`
- `stg_billing__subscriptions`
- `stg_billing__invoices`
- `stg_billing__invoice_lines`
- `stg_billing__payments`
- `stg_billing__refunds`

The staging layer should handle only:

- Renaming
- Type conversion
- Timestamp normalization
- Casing and whitespace cleanup
- Null standardization
- Basic derived fields that do not encode major business rules

Avoid aggregations and cross-source joins in staging.

# 8. Build the intermediate business logic

Add:

- `int_subscription_periods`
- `int_customer_subscription_history`
- `int_invoice_line_totals`
- `int_invoice_payment_status`
- `int_payment_refund_netting`

Potential additional models:

- `int_subscription_months`
- `int_subscription_plan_changes`
- `int_customer_identity_resolution`
- `int_invoice_balance`
- `int_payments_deduplicated`

These models should encode reusable rules for:

- Billable subscription periods
- Active-period overlap
- Monthly normalization of annual plans
- Invoice totals
- Payment attempts
- Net collected cash
- Remaining invoice balances
- Refund allocation
- Plan changes
- Duplicate handling

# 9. Build the target marts

Add the planned dimensional model:

### Dimensions

- `dim_customers`
- `dim_organizations`
- `dim_plans`
- `dim_dates`

### Facts

- `fct_subscriptions`
- `fct_invoices`
- `fct_payments`
- Possibly `fct_refunds`

### Marts

- `mart_monthly_revenue`
- `mart_customer_metrics`
- `mart_invoice_reconciliation`

Project 1's monthly-revenue mart should remain relatively foundational. Advanced revenue movements and retention can be expanded in Project 2.

# 10. Decide the historical strategy

Document which source records can change:

- Customer country and organization details
- Subscription plan and status
- Renewal and cancellation dates
- Invoice status
- Payments subsequently refunded

Then implement:

- One well-defined dbt snapshot, probably customers or subscriptions
- Effective-from/effective-to dates
- A current-record flag
- Direct updates where history is unnecessary
- At least one incremental model if it adds genuine value

The existing customer snapshot pattern can be adapted, but it needs subscription-domain reasoning and tests.

# 11. Expand dbt testing

Current tests provide a good technical starting point but do not test subscription business logic.

Add:

### Structural tests

- Unique and non-null primary keys
- Foreign-key relationships
- Accepted status values
- Declared model grains
- Required timestamps and monetary values

### Financial tests

- Invoice totals equal invoice-line totals
- Invoice totals are non-negative
- Successful payments are positive
- Net refunds do not exceed collected payments without an explicit exception
- Outstanding balance equals invoice total minus net collected amount
- Aggregate mart revenue reconciles to underlying facts

### Subscription tests

- Subscription end cannot precede start
- Current period cannot precede subscription creation
- Annual plans normalize correctly to monthly value
- Active subscriptions overlap the reporting period
- Trials are handled according to the documented rule
- Cancelled subscriptions stop contributing at the correct date
- Reactivations are not incorrectly classified as new subscriptions

### Failure demonstrations

Include at least one documented procedure that deliberately introduces bad data and shows the corresponding test failing.

# 12. Correct revenue terminology

The current repository mixes:

- Order value
- Recognized revenue
- Completed-order revenue
- Cash collected

These are not interchangeable.

The subscription version should distinguish:

- Contracted recurring value
- Invoiced revenue
- Collected cash
- Refunded cash
- Outstanding balance
- Recognized revenue, only if genuine recognition rules are implemented

Avoid claiming revenue recognition unless accounting-period allocation and relevant rules actually exist.

# 13. Add environment separation

The dbt profile currently has only a `dev` target.

Add or document:

- Developer schemas isolated by user or environment
- A CI target
- A production-style target or clear production configuration example
- Environment-variable-driven credentials
- Different schema naming where appropriate

No real cloud production deployment is required for Project 1.

> **Note (Phase 1, already done):** a distinct `ci` target now exists
> (schema `analytics_ci`), used by GitHub Actions instead of reusing
> `dev`.

# 14. Improve CI

The existing CI already runs linting, type checking, ingestion, dbt build, and freshness. Add:

- Python unit tests
- Generator validation
- Determinism test
- dbt dependency caching where useful
- A dedicated CI dbt target
- SQLFluff configured explicitly for dbt templating
- Optional state-based modified-model builds once a stable manifest workflow exists
- Clear failure output
- Verification that generated documentation succeeds

Keep a full build available because the project is small.

# 15. Add a dashboard

There is currently an exposure describing a dashboard, but no dashboard implementation.

Add one small Metabase or Streamlit dashboard answering the agreed questions. At minimum:

- Active customers
- Active subscriptions
- Monthly normalized recurring revenue
- Invoiced versus collected value
- Outstanding invoice value
- Refunds
- Revenue by plan
- Revenue or customers by country

The dashboard should remain thin: business logic belongs in dbt, not in dashboard formulas.

# 16. Add traceability

Demonstrate that one dashboard value can be traced through:

`dashboard → mart → fact/intermediate model → staging model → raw source rows`

Document one worked example in the README or case study.

Update the dbt exposure so that its URL and dependencies correspond to a real dashboard.

# 17. Complete dbt documentation

Add:

- Descriptions for every model
- Descriptions for important columns
- Source descriptions
- Grain statements
- Business definitions
- Known limitations
- Ownership information
- Exposure dependencies
- Generated lineage screenshot or diagram

The README should explain modeling choices and trade-offs, not merely setup commands.

# 18. Update the repository README

The final README should include:

- Business problem
- Architecture diagram
- Source systems
- Model layers
- Key business questions
- Metric-definition summary
- Important modeling decisions
- Test strategy
- Intentional data-quality problems
- How to run the project
- How to view dbt documentation
- How to view the dashboard
- Example failure
- Traceability example
- Limitations and deferred features
- What you personally designed and why

Remove or revise any claims unsupported by the implementation.

# 19. Perform the cleanup pass

After the warehouse works:

- Remove obsolete retail models and terminology
- Remove duplicated SQL
- Simplify unnecessary abstractions
- Break up oversized functions
- Standardize naming
- Remove unused dependencies
- Replace generic AI-style prose
- Review every generated file
- Check that comments explain decisions rather than restating code
- Verify that tests examine business behavior rather than mirror implementation

# 20. Satisfy the acceptance criteria

Project 1 is complete when a new user can:

1. Clone the repository.
2. Install dependencies.
3. Start PostgreSQL with one command.
4. Generate and ingest the data.
5. Run `dbt build`.
6. See all tests pass.
7. Generate and browse dbt documentation.
8. Open the dashboard.
9. Answer the agreed business questions.
10. Trace a dashboard metric to raw records.
11. Insert a documented bad record and see a test fail.
12. Understand the design from the documentation without reading every source file.

## Recommended implementation order

1. Freeze the business and metric definitions.
2. Define source contracts and model grains.
3. Rebuild the generator for customers, plans, and subscriptions.
4. Add CRM and billing ingestion.
5. Build subscription staging models.
6. Build `int_subscription_periods`.
7. Build `fct_subscriptions`, customer and plan dimensions.
8. Add active-customer and basic monthly-revenue marts.
9. Add invoices, invoice lines, and payments.
10. Add payment/refund reconciliation.
11. Complete tests and Python test coverage.
12. Add the dashboard and traceability example.
13. Finish CI, documentation, and cleanup.

The most important immediate work is not more scaffolding: it is fixing the business definitions, source contracts, and model grains before replacing the retail generator.
