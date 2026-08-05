{% test not_implausibly_large(model, column_name, max_value) %}
-- Generic custom test: fails if any row has column_name > max_value.
-- Row-level metric-anomaly check — see docs/reliability_strategy.md
-- for how max_value is chosen per column (grounded in the actual
-- product/plan catalog, not an arbitrary round number).
select *
from {{ model }}
where {{ column_name }} > {{ max_value }}
{% endtest %}
