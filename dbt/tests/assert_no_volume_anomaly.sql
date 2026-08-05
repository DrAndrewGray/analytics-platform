-- Singular test: no closed period may show a >=40% volume drop against
-- its own 3-period trailing average, once that average is at least 10
-- rows (see mart_volume_anomalies.sql for how both numbers were
-- calibrated from this warehouse's actual history). Fails (returns a
-- row) for every anomalous source/period pair, so a failure names
-- exactly which source and period to investigate — see
-- docs/incidents/ for a worked example of this test catching an
-- injected volume collapse.
select
    source_name,
    period_id,
    period_start_date,
    row_count,
    trailing_avg_row_count,
    pct_change_vs_trailing_avg
from {{ ref('mart_volume_anomalies') }}
where is_anomaly
