-- Singular test: a table-level business invariant rather than a row-level
-- check. Fails (returns a row) if total recognized revenue across all
-- completed orders ever goes negative, which should be structurally
-- impossible given how order_amount is derived.
select sum(order_amount) as total_revenue
from {{ ref('fct_orders') }}
where order_status = 'completed'
having sum(order_amount) < 0
