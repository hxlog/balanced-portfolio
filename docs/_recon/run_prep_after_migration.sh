#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 迁移 63 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/63_percentile_windows.sql" 2>&1 | tail -3
echo "=== 重算分位 ==="
timeout 1500 .venv/bin/python scripts/revamp_data_prep.py > /tmp/revamp_prep2.log 2>&1
echo "exit=$?"
grep -aE "intro updated|industry updated|as_of|percentiles done" /tmp/revamp_prep2.log | tail -6
echo "=== 分位窗口 ==="
su - postgres -c "psql -d postgres -c \"select window_key, count(*) rows, count(pct) with_pct from bp_index_percentile where as_of_date = (select max(as_of_date) from bp_index_percentile) group by 1 order by 1\""
