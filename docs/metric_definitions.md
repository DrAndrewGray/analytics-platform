# Metric definitions and modeling decisions

Written before the models, per the Phase 2 spec's own instruction: define
the rules first, build to them second, rather than let the SQL
accidentally decide what a metric means.

## Data model: subscriptions as phases, not mutable rows

A subscription is modeled as a sequence of **phases** — one row per
continuous stretch at a fixed plan. A phase ends when the customer
upgrades, downgrades, cancels, or pauses; a new phase begins on
reactivation. Phases sharing a `subscription_chain_id` are the same
underlying customer relationship across those changes.

This is the one design decision everything else depends on, so it's
worth justifying: modeling subscriptions as a single row with mutable
`plan_id`/`status` columns would destroy the history needed to classify
MRR movements (an upgrade is only detectable as "the MRR went up" if you
can see the before-and-after). A phase table makes every plan change a
first-class, queryable, dated event — the join key for MRR-movement
classification is a phase's `phase_type`/`ended_reason`, not a
snapshot diff.

## Active customer / active subscription

A subscription phase is **active** as of a date if
`phase_start_date <= date` and (`phase_end_date is null` or
`phase_end_date > date`). An **active customer** has at least one active
subscription phase as of that date. Trialing phases count as active
subscriptions (the customer has access) but contribute $0 to MRR (see
below) — "active" and "paying" are different questions.

## MRR (Monthly Recurring Revenue)

MRR is **contracted recurring value**, not cash. It is derived from the
subscription phase, not from invoices or payments — an unpaid invoice
still represents contracted MRR; a refund doesn't retroactively erase it
(refunds affect collected-cash metrics, not MRR). This mirrors Phase 1's
core decision to keep recognized value and cash collected as separate,
explicitly reconciled numbers rather than one number quietly standing in
for both.

- **Monthly plans**: MRR = plan price.
- **Annual plans**: MRR = annual price / 12 (normalized to a monthly
  figure so monthly and annual plans are comparable).
- **Trials**: MRR = $0 while `is_trial = true`, regardless of the plan's
  list price. MRR begins the month the trial converts to a paid phase.
- **MRR is measured at the calendar-month grain**: a phase active for
  any part of a month contributes its full monthly MRR to that month.
  Plan changes are not prorated mid-month — a phase's MRR is constant
  for every month it's active, and a new month's MRR reflects whatever
  phase is active by the start of that month. This keeps the movement
  classification (below) unambiguous: every month has exactly one MRR
  value per subscription chain.

## MRR movements

For each subscription chain, each month is classified by comparing the
active phase's MRR to the prior month's:

| Movement | Condition |
|---|---|
| **New MRR** | First phase ever for this chain, first month active |
| **Expansion MRR** | Same chain, this month's MRR > last month's (upgrade) |
| **Contraction MRR** | Same chain, this month's MRR < last month's, still active (downgrade) |
| **Reactivation MRR** | Chain had a prior phase that ended, gap of ≥1 month, then a new phase starts | 
| **Churned MRR** | Chain's phase ended (`ended_reason` is `cancelled` or `paused`) and no new phase starts that month |

**The bridge these must satisfy, every month:**

```
opening_mrr + new_mrr + expansion_mrr + reactivation_mrr
  - contraction_mrr - churned_mrr = closing_mrr
```

This is tested directly (`mart_mrr_movements`) — not just documented and
hoped for.

## Revenue retention

- **Gross revenue retention (GRR)**: `(opening_mrr - contraction_mrr -
  churned_mrr) / opening_mrr` for a cohort/period. Never exceeds 100% —
  expansion is excluded on purpose, since GRR asks "how much would we
  have kept with zero upsell."
- **Net revenue retention (NRR)**: `(opening_mrr - contraction_mrr -
  churned_mrr + expansion_mrr) / opening_mrr`. Can exceed 100%.

## Cohort retention

A customer's cohort is the calendar month of their **first-ever**
subscription phase (`phase_type = 'new'`). Retention for a cohort at
month N is: (customers from that cohort with an active phase in
cohort-month + N) / (total customers in that cohort).

## Customer lifetime value (CLV)

Deliberately simple, and documented as such rather than dressed up as
more rigorous than it is:

```
CLV = average MRR per active customer / monthly churn rate
```

This is the standard "simple SaaS CLV" formula. It assumes constant
churn and MRR going forward, which is a real simplification — a cohort-
survival-curve-based CLV would be more accurate but is a materially
bigger modeling project. Documenting the formula's assumption here is
the point: a number without its assumptions attached is worse than no
number.

## Invoices, payments, refunds — the cash side

Same reconciliation discipline as Phase 1, applied to invoices instead
of orders:

- **Invoiced revenue**: sum of invoice line amounts, at invoice-issue
  date.
- **Collected cash**: sum of `succeeded` payments, at payment date.
- **Refunded amount**: sum of refunds, at refund date.
- **Outstanding balance**: invoiced − (collected − refunded), per
  invoice. Can be nonzero for underpaid, failed, or not-yet-paid
  invoices.
- **Net collected**: collected − refunded. This is what actually stayed
  in the business.

Partial payments and partial refunds are both modeled — an invoice's
outstanding balance is a first-class, tested number, not an
approximation.

## Explicit non-decisions (deferred, not forgotten)

- **Tax**: out of scope. No tax column exists; amounts are treated as
  the full contracted/invoiced value. Adding tax later means adding a
  column and updating every downstream sum, not un-deciding anything.
- **Currency**: single currency (USD) for this phase. `plans.currency`
  exists as a column for forward compatibility but every row is `USD`.
- **Which date controls each metric**: MRR uses the phase's active
  months; invoiced revenue uses invoice date; collected cash uses
  payment date; refunds use refund date. Each metric answers a
  different question ("what did we contract for," "what did we bill,"
  "what did we actually get paid," "what did we give back") and mixing
  their dates would blur those questions together.
