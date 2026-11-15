#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 迁移 68 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/68_fund_nav_risk.sql" 2>&1 | tail -2
su - postgres -c "psql -d bp_mig_test -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/68_fund_nav_risk.sql" 2>&1 | tail -1
pm2 restart bp-api >/dev/null
sleep 4
curl -s -o /dev/null -w "api:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
echo "=== 启动基金净值回填（后台） ==="
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_fund_nav.py > /tmp/fund_nav_backfill.log 2>&1 < /dev/null &
echo launched
sleep 25
tail -4 /tmp/fund_nav_backfill.log
