#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 运行数据准备（含分位重算） ==="
timeout 1500 .venv/bin/python scripts/revamp_data_prep.py > /tmp/revamp_prep.log 2>&1
echo "exit=$?"
tail -12 /tmp/revamp_prep.log
echo "=== 分位窗口 ==="
su - postgres -c "psql -d postgres -c \"select window_key, count(*) rows, count(pct) with_pct from bp_index_percentile where as_of_date = (select max(as_of_date) from bp_index_percentile) group by 1 order by 1\""
