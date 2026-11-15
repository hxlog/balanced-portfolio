#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f csindex_quote_backfill || true
sleep 1
cat > /etc/cron.d/bp-csindex-quotes <<'EOF'
# 每小时经 SG relay 慢速补齐中证官网行情（WAF 限流严格：20s/只，单次 50 分钟）
20 * * * * root cd /opt/balanced-portfolio && BP_HTTP_PROXY=http://127.0.0.1:10809 BP_CS_DELAY=20 BP_CS_BUDGET=3000 nice -n 15 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py >> /var/log/bp-csindex-quotes.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-csindex-quotes
echo "--- 启动慢速回填 ---"
BP_HTTP_PROXY=http://127.0.0.1:10809 BP_CS_DELAY=20 BP_CS_BUDGET=3000 setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py > /tmp/csindex_relay4.log 2>&1 < /dev/null &
sleep 50
grep -aE "missing|progress|skip-invalid|WAF|done" /tmp/csindex_relay4.log | tail -5
date