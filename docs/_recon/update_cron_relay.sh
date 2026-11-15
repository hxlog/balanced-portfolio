#!/usr/bin/env bash
set -uo pipefail
cat > /etc/cron.d/bp-csindex-quotes <<'EOF'
# 每小时经 SG relay 用中证官网行情补齐缺失指数（直连被 WAF 403；relay 出口可用）
20 * * * * root cd /opt/balanced-portfolio && HTTPS_PROXY=http://127.0.0.1:10809 HTTP_PROXY=http://127.0.0.1:10809 NO_PROXY=127.0.0.1,localhost,81.71.158.239 nice -n 15 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py >> /var/log/bp-csindex-quotes.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-csindex-quotes
echo "--- 回填进度 ---"
grep -aE "progress|budget|done|WAF" /tmp/csindex_relay.log | tail -4
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
free -h | head -2