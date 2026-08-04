-- One row per anonymous_id, mapping it to the customer it resolves to
-- (null if never identified). max() is safe here specifically because
-- each anonymous_id should only ever carry one distinct non-null
-- customer_id — see the dedicated test asserting exactly that
-- (_intermediate__events_models.yml), which is what would actually catch
-- it if that assumption ever stopped holding.
select
    anonymous_id,
    max(customer_id) as resolved_customer_id
from {{ ref('stg_events__events') }}
group by anonymous_id
