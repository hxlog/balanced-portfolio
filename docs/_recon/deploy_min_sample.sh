#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api bp_ingest ddl scripts
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: 分位样本门槛按窗口区分(1y=40)；迁移 63 扩展窗口约束" || true
pm2 restart bp-api >/dev/null
sleep 4
echo "=== 重算分位 ==="
timeout 1500 .venv/bin/python scripts/revamp_data_prep.py > /tmp/revamp_prep3.log 2>&1
echo "exit=$?"
grep -aE "percentiles done" /tmp/revamp_prep3.log | tail -2
echo "=== 分位窗口 ==="
su - postgres -c "psql -d postgres -c \"select window_key, count(*) rows, count(pct) with_pct from bp_index_percentile where as_of_date = (select max(as_of_date) from bp_index_percentile) group by 1 order by 1\""
