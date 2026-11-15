#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 迁移 62 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/62_index_industry.sql" 2>&1 | tail -3
echo "=== 数据准备（简介/行业/分位） ==="
timeout 1500 .venv/bin/python scripts/revamp_data_prep.py 2>&1 | grep -aE "intro updated|industry updated|as_of|percentiles" | tail -20
echo "=== 分位覆盖 ==="
su - postgres -c "psql -d postgres -c \"select window_key, metric, count(*) rows, count(pct) with_pct from bp_index_percentile where as_of_date = (select max(as_of_date) from bp_index_percentile) group by 1,2 order by 1,2\""
echo "=== 简介/行业 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*) filter (where intro is not null and btrim(intro) <> ''), count(*) filter (where industry is not null), count(*) from bp_index_master\""
free -h | head -2
