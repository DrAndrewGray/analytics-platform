-- The MRR bridge must hold exactly, every month:
--   opening + new + expansion + reactivation - contraction - churned = closing
-- mart_mrr_movements computes both sides; this fails if they ever
-- disagree, rather than relying on someone eyeballing the mart.
select *
from {{ ref('mart_mrr_movements') }}
where closing_mrr != computed_closing_mrr
