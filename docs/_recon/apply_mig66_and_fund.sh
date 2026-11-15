#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 迁移 66（生产 + 测试库） ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/66_fund_details_health.sql" 2>&1 | tail -3
su - postgres -c "psql -d bp_mig_test -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/66_fund_details_health.sql" 2>&1 | tail -2
pm2 restart bp-api >/dev/null
sleep 4
curl -s -o /dev/null -w "api:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
echo "=== 启动基金全字段回填（后台） ==="
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_fund_data.py --all > /tmp/fund_backfill.log 2>&1 < /dev/null &
echo launched
sleep 20
tail -4 /tmp/fund_backfill.log
