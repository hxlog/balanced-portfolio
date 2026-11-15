#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/repositories_valuation.py scripts/index_quote_incremental.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "perf/feat: 估值页行情改用原始行情表；新增指数行情每日增量脚本" || true
pm2 restart bp-api >/dev/null
sleep 4
echo "--- api timing ---"
for i in 1 2; do curl -s -o /dev/null -w "run$i: %{http_code} %{time_total}s\n" "http://127.0.0.1:8000/api/valuation/indices?limit=600"; done
echo "--- coverage ---"
curl -s "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('close',f('close_price'),'7d',f('change_7d_pct'),'52w',f('high_52w'))"
echo "--- install daily cron ---"
cat > /etc/cron.d/bp-index-quotes <<'EOF'
# 每日收盘后更新 521 只估值指数的行情（单进程限速；页面直接读原始行情表）
10 16 * * 1-5 root cd /opt/balanced-portfolio && nice -n 10 ionice -c2 -n7 .venv/bin/python scripts/index_quote_incremental.py >> /var/log/bp-index-quotes.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-index-quotes
cat /etc/cron.d/bp-index-quotes