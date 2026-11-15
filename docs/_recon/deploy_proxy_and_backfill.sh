#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f csindex_quote_backfill || true
pkill -f csindex_drip || true
sleep 1
git add -A bp_ingest/http_session.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: BP_HTTP_PROXY 显式代理开关（中证官网经 SG relay）" || true
echo "--- 测试代理开关 ---"
BP_HTTP_PROXY=http://127.0.0.1:10809 timeout 90 .venv/bin/python - <<PY
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
from bp_ingest.http_session import install_hardened_session
install_hardened_session()
import requests
r = requests.get("https://www.csindex.com.cn/csindex-home/perf/index-perf", params={"indexCode": "000300", "startDate": "20260101", "endDate": "20261114"}, timeout=40)
rows = (r.json().get("data") or []) if r.status_code == 200 else []
print("status", r.status_code, "rows", len(rows))
PY
echo "--- 启动 relay 回填 ---"
BP_HTTP_PROXY=http://127.0.0.1:10809 setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py > /tmp/csindex_relay2.log 2>&1 < /dev/null &
sleep 40
grep -aE "index symbols|progress|WAF|budget|done|fetch fail" /tmp/csindex_relay2.log | tail -5
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""