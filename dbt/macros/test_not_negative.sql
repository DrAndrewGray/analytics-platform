{% test not_negative(model, column_name) %}
-- Generic custom test: fails if any row has column_name < 0.
select *
from {{ model }}
where {{ column_name }} < 0
{% endtest %}
