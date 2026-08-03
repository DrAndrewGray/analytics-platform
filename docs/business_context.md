# Business context: Meridian+ Membership

Phase 1 modeled Meridian as a retailer selling one-off orders. Phase 2
extends the same fictional company with a second revenue line:
**Meridian+**, a monthly/annual membership program (free shipping,
member pricing, early access) billed as a recurring subscription. This
is a common real-world pattern — a retailer running a loyalty/membership
subscription alongside its one-off order business (Amazon Prime is the
obvious analogue) — and it's why Phase 2 extends the existing warehouse
rather than standing up an unrelated SaaS company from scratch.

## What's being modeled

- **Customers** are shared with Phase 1 (`raw.customers`) — a Meridian+
  member is still a Meridian customer, and may or may not also place
  one-off orders.
- **Plans**: a small number of monthly and annual membership tiers.
- **Subscriptions**: a customer's membership over time. Customers can
  start, trial, upgrade/downgrade between tiers, cancel, and later
  reactivate. Modeled as a sequence of **phases** (see
  `metric_definitions.md`) rather than a single mutable row, so that
  plan changes are first-class, queryable events instead of overwritten
  state.
- **Invoices / invoice lines**: issued per billing period per
  subscription phase.
- **Payments**: attempts against invoices — successful, failed, retried.
- **Refunds**: full or partial, against a specific payment.

## Reporting stakeholders

- **Finance**: invoiced vs. collected cash, outstanding balances,
  refunds — same reconciliation discipline as Phase 1's orders, applied
  to recurring billing.
- **Commercial / RevOps**: MRR, MRR movements (new/expansion/
  contraction/reactivation/churn), net and gross revenue retention.
- **Product / Customer Success**: cohort retention, customer lifetime
  value, upgrade/downgrade patterns.

## Explicitly out of scope for this phase

Per the Phase 2 spec, these are deliberately deferred, not overlooked:

- Product-event analytics, marketing attribution, support data
- A semantic layer / AI assistant
- Multi-currency (single currency, USD, for this phase)
- Streaming ingestion, Terraform/Kubernetes, cloud-scale orchestration
- An interactive dashboard implementation (an `exposure` describes one,
  matching Phase 1's precedent of deferring the actual BI layer)
