# Metric definitions and modeling decisions — product events

## Identity resolution

Every event carries an `anonymous_id`. Some events also carry a
`customer_id`, starting from whichever event first identifies the
visitor (a `signup` or `login` event) onward.

**Resolution rule**: for a given `anonymous_id`, if *any* event carries a
non-null `customer_id`, every event sharing that `anonymous_id` —
including ones that happened *before* the identifying event — resolves
to that `customer_id`. This is what makes pre-signup browsing behavior
attributable to the customer it belonged to, which is the entire point
of tracking anonymous activity in the first place.

**A customer can have more than one `anonymous_id`** (different device,
cleared cookies, different browser). Resolution is computed per
`anonymous_id`, not assumed to be one-to-one — `int_identity_resolution`
produces an `anonymous_id -> resolved_customer_id` mapping, and a given
`resolved_customer_id` can legitimately appear against several
`anonymous_id`s.

An `anonymous_id` that never has an identifying event stays
unresolved (`resolved_customer_id` is null) — most anonymous browsing
never converts, and pretending otherwise would be fabricating identity,
not resolving it.

## Sessionization

Not tracked at the source (see `docs/business_context_events.md`).
Computed per `anonymous_id`: a new session starts whenever the gap since
that `anonymous_id`'s previous event exceeds **30 minutes** — the
standard industry default (GA4, Amplitude, Mixpanel all use it). Session
boundaries are computed *before* identity resolution, on the raw
`anonymous_id`, since that's the actual client that generated a
contiguous burst of activity; sessions are not merged across different
`anonymous_id`s that later resolve to the same customer.

## Duplicate events

Analytics beacons double-fire in the real world (page reload, retry on a
flaky connection). An event is treated as a duplicate — and excluded
from counts — if it shares the same `anonymous_id`, `event_type`,
`product_id` (if any), and `event_timestamp` as another event. This is
deliberately strict (exact timestamp match) rather than a fuzzy
time-window de-dup, since the synthetic duplicates this project
generates are exact re-fires; a real pipeline would need a wider,
fuzzier window, which is a reasonable extension but not implemented here.

## Funnel

The core funnel, in order: `product_view` → `add_to_cart` →
`checkout_start` → `purchase`. A visitor (resolved customer or
still-anonymous `anonymous_id`) is counted at a funnel step if they have
at least one matching event on a given day; conversion rate between two
steps is (visitors reaching the later step) / (visitors reaching the
earlier step), for the same day.

**This measures same-day step *presence*, not an ordered, causally-linked
journey.** A visitor who views product A in the morning and buys
unrelated product B that evening still counts as completing every step
that day — nothing here confirms the view led to the cart add, or the
cart add led to that specific purchase. A true sequential funnel would
need to link specific view → cart → purchase events to each other (e.g.
same product, strictly increasing timestamps, no intervening funnel-reset
event), which is a real, heavier modeling task deliberately deferred
here. Read `view_to_purchase_rate` as "purchased at all on a day they
also viewed something," not "viewing X caused purchasing Y."

`purchase` events carry the `order_id` of the resulting Phase 1 order —
this is the one point where the event stream and the transactional
warehouse connect. A purchase event without a same-day `product_view` or
`add_to_cart` event is possible (e.g. a repeat-order customer going
straight to checkout) and is not treated as an error.

## Activation

A customer is **activated** if their first `purchase` event *on or after
their first `signup` event* happens within 14 days of that signup. This
is a single, deliberately simple threshold — a real product-activation
definition usually involves several distinct actions ("aha moments"),
not just a purchase, but a single funnel-completion threshold is enough
to demonstrate the calculation without inventing product behavior this
dataset doesn't actually model.

The "on or after signup" qualifier is load-bearing, not decorative: a
customer's globally-earliest purchase could predate their signup
entirely (e.g. a guest checkout later followed by account creation).
Using that earlier purchase as "first purchase" would produce a negative
days-to-purchase and could satisfy the 14-day window by construction,
marking someone activated based on activity that happened before they
ever signed up. `mart_activation` filters purchases to
`event_timestamp >= first_signup_at` before taking the minimum, and
`days_to_first_purchase` is tested to never be negative.
