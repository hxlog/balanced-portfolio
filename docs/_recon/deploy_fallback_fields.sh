#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/repositories_valuation.py scripts/retry_missing_quotes.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: 7日/52周涨跌回退平安口径；新增缺失行情每小时重试脚本" || true
pm2 restart bp-api >/dev/null
sleep 5
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',len(d),'| close',f('close_price'),'| 7d',f('change_7d_pct'),'| 52wRet',f('change_52w_pct'),'| pos',f('position_52w_pct'))"
echo "--- install hourly retry cron ---"
cat > /etc/cron.d/bp-index-quotes-retry <<'EOF'
# 每小时尝试补齐缺失行情的指数（EM 临时封禁解除后自动恢复）
25 * * * * root cd /opt/balanced-portfolio && nice -n 15 ionice -c2 -n7 .venv/bin/python scripts/retry_missing_quotes.py >> /var/log/bp-index-quotes-retry.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-index-quotes-retry
cat /etc/cron.d/bp-index-quotes-retry