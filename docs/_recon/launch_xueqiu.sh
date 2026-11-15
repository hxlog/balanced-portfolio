#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 应用迁移 61 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/61_xueqiu_index_source.sql" 2>&1 | tail -2
echo "=== 启动雪球回填 ==="
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/xueqiu_quote_backfill.py > /tmp/xueqiu_backfill.log 2>&1 < /dev/null &
sleep 60
grep -aE "index symbols|ok |skip|budget|done|fetch fail" /tmp/xueqiu_backfill.log | tail -8
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
free -h | head -2