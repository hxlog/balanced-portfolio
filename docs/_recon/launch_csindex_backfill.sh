#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 应用迁移 60 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f ddl/60_csindex_perf_source.sql" 2>&1 | tail -2
echo "=== 启动中证官网行情回填 ==="
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py > /tmp/csindex_quotes.log 2>&1 < /dev/null &
sleep 40
tail -4 /tmp/csindex_quotes.log
free -h | head -2