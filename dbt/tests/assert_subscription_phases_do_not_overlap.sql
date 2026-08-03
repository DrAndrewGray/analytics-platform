-- Within a subscription chain, one phase's end date should never fall
-- after the *next* phase's start date — that would mean two phases of
-- the same chain were simultaneously "the" active phase for longer than
-- the single allowed same-month transition (trial ending and the paid
-- phase starting), which would make MRR movement classification
-- ambiguous rather than just requiring the "authoritative phase" tie-break.
with ordered as (
    select
        subscription_id,
        subscription_chain_id,
        phase_start_date,
        phase_end_date,
        lead(phase_start_date) over (
            partition by subscription_chain_id order by phase_start_date
        ) as next_phase_start_date
    from {{ ref('fct_subscriptions') }}
)

select *
from ordered
where
    phase_end_date is not null
    and next_phase_start_date is not null
    and phase_end_date > next_phase_start_date
