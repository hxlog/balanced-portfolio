#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
cat > /etc/cron.d/bp-csindex-quotes <<'EOF'
# 每小时用中证官网行情补齐缺失指数（慢速 drip：8~12s/只，403 指数退避；单次预算 50 分钟）
20 * * * * root cd /opt/balanced-portfolio && nice -n 15 ionice -c2 -n7 .venv/bin/python scripts/csindex_drip.py >> /var/log/bp-csindex-quotes.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-csindex-quotes
cat /etc/cron.d/bp-csindex-quotes
echo "--- drip 进度 ---"
grep -aE "ok |403 backoff|done" /tmp/csindex_drip.log | tail -4
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""