#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 迁移 67 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/67_market_valuation_index.sql" 2>&1 | tail -2
su - postgres -c "psql -d bp_mig_test -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/67_market_valuation_index.sql" 2>&1 | tail -1
echo "=== 计算 MVI ==="
.venv/bin/python scripts/compute_mvi.py 2>&1 | grep -v "UserWarning\|read_sql" | tail -3
echo "=== 重启 API + 验证 ==="
pm2 restart bp-api >/dev/null
sleep 4
.venv/bin/python - <<'PY'
import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/overview?window=5y", timeout=60))
mvi = (d.get("meta") or {}).get("mvi") or {}
print("latest:", json.dumps(mvi.get("latest"), ensure_ascii=False)[:500])
print("history:", len(mvi.get("history") or []))
PY
echo "=== cron ==="
cat > /etc/cron.d/bp-mvi <<'EOF'
# 每工作日 17:05 刷新市场估值指数 MVI（先算后落库）
5 17 * * 1-5 root cd /opt/balanced-portfolio && nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/compute_mvi.py >> /var/log/bp-mvi.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-mvi
echo installed
