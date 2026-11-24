-- 今日（或指定交易日）各 dataset 波次 SLA 记录
-- 用法: psql -f scripts/sla_report.sql -v d='2026-11-24'
SELECT dataset, adjust,
       min(started_at)::timestamp(0) AS first_start,
       max(finished_at)::timestamp(0) AS last_finish,
       count(*) FILTER (WHERE status='ok') AS ok_runs,
       count(*) AS runs,
       max(achieved_coverage)::numeric(6,4) AS best_coverage,
       sum(rows_written) AS rows_written
FROM bp_etl_run
WHERE trade_date = :'d'
GROUP BY dataset, adjust
ORDER BY dataset, adjust;
