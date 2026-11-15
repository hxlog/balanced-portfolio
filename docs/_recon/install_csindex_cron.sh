#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f csindex_quote_backfill || true
sleep 1
cat > /etc/cron.d/bp-csindex-quotes <<'EOF'
# 每 2 小时尝试用中证官网行情补齐缺失指数（WAF 冷却后自动恢复；单次预算 10 分钟）
35 */2 * * * root cd /opt/balanced-portfolio && nice -n 15 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py >> /var/log/bp-csindex-quotes.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-csindex-quotes
cat /etc/cron.d/bp-csindex-quotes
echo "--- coverage now ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""