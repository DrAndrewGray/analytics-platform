# Business context: product events

Phase 3 extends the warehouse again, with clickstream/product-event data
from Meridian's website: page views, searches, product views, cart
activity, checkout, and the signup/login moments that turn an anonymous
visitor into a known customer (`raw.customers`, shared with Phase 1/2 —
an identified visitor is still a Meridian customer).

## What's being modeled

- **Events**: one row per tracked interaction. `anonymous_id` (a
  cookie-like identifier) is always present; `customer_id` is null until
  the visitor signs up or logs in, then populated on events from that
  point forward — exactly how a real client-side analytics SDK behaves.
- **Sessions**: not tracked at the source. A real pipeline would compute
  this downstream from raw events, so this one does too — see
  `docs/metric_definitions_events.md` for the gap-based definition.
- **Identity**: an anonymous visitor can generate events across multiple
  anonymous IDs before ever being identified (different browser, cleared
  cookies, different device) and, once identified, that history should
  resolve back to one customer. This — not the funnel math — is the hard
  part of this domain, and the reason this phase exists: to demonstrate
  handling identity resolution correctly, not just counting pageviews.

## Reporting stakeholders

- **Product / Growth**: funnel conversion (view → cart → purchase),
  activation (time from signup to first purchase).
- **Data engineering peers**: whether identity resolution and
  sessionization are implemented correctly, since a wrong join here
  silently corrupts every downstream funnel and retention number.

## Explicitly out of scope for this phase

- Marketing attribution (UTM/campaign modeling) — a different, larger
  problem than session/identity stitching.
- Real-time/streaming ingestion — batch, same as every other phase here.
- A/B test analysis.
