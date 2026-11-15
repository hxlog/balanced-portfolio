#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
cat > /etc/cron.d/bp-fund-nav <<'EOF'
# 每工作日 16:50 增量抓取基金净值并重算风险指标（净值/波动/回撤/跟踪误差/信息比率）
50 16 * * 1-5 root cd /opt/balanced-portfolio && nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_fund_nav.py >> /var/log/bp-fund-nav.log 2>&1 && nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/compute_fund_risk.py >> /var/log/bp-fund-risk.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-fund-nav
echo installed
echo "=== 净值回填进度 ==="
pgrep -fc backfill_fund_nav || echo done
tail -2 /tmp/fund_nav_backfill2.log | tr -d "\r"
su - postgres -c "psql -d postgres -tAc \"select count(distinct fund_code), count(*), (select count(*) from bp_fund_risk) from bp_fund_nav_daily\""
