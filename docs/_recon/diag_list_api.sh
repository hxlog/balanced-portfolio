#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== health ==="
curl -s -o /dev/null -w "health:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
echo "=== indices 响应头 ==="
curl -s -o /tmp/idx.json -w "indices:%{http_code} bytes:%{size_download}\n" --max-time 40 "http://127.0.0.1:8000/api/valuation/indices?limit=3"
head -c 300 /tmp/idx.json
echo
echo "=== API 错误日志 ==="
tail -20 /root/.pm2/logs/bp-api-error.log | grep -iE "error|exception|traceback" | tail -5
echo "=== 直接测 SQL 函数 ==="
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
from bp_ingest.config import load_config
from bp_ingest.db import connect
from bp_api import repositories_valuation as repo
app = load_config()
with connect(app.db) as conn:
    try:
        rows, total = repo.get_index_list(conn, query=None, index_type=None, only_with_etf=False, only_with_valuation=False, limit=2, offset=0)
        print("ok rows:", len(rows), "total:", total)
        if rows:
            r = rows[0]
            print("fields:", r.get("index_code"), r.get("roe_ttm"), r.get("fund_aum"), r.get("fund_count"))
    except Exception as exc:
        print("SQL FAIL:", type(exc).__name__, str(exc)[:500])
PY
