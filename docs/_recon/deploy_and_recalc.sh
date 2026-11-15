#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api bp_ingest ddl scripts
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: 分位窗口扩展为 1/3/5/10 年+全历史；指数行业分类迁移 62；重构数据准备脚本" || true
pm2 restart bp-api >/dev/null
sleep 5
curl -s -o /dev/null -w "api:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
echo "=== 重算分位（含 1y/3y） ==="
timeout 1500 .venv/bin/python scripts/revamp_data_prep.py 2>&1 | grep -aE "intro updated|industry updated|as_of|percentiles done" | tail -6
echo "=== 分位覆盖 ==="
su - postgres -c "psql -d postgres -c \"select window_key, count(*) rows, count(pct) with_pct from bp_index_percentile where as_of_date = (select max(as_of_date) from bp_index_percentile) group by 1 order by 1\""
