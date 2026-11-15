#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 停止卡住的修复进程 ==="
pkill -f repair_stale_quotes || true
sleep 1
echo "=== 更新 cron：每 2 小时尝试修复滞后行情 ==="
cat > /etc/cron.d/bp-data-health <<'EOF'
# 每工作日 17:10 检查指数行情覆盖率并刷新极值表
10 17 * * 1-5 root cd /opt/balanced-portfolio && nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/quote_coverage_watch.py >> /var/log/bp-data-health.log 2>&1
# 每 2 小时尝试修复滞后指数行情（新浪直连 / 中证 relay 双通道，外部源恢复后自动补齐；单次预算 20 分钟）
15 */2 * * * root cd /opt/balanced-portfolio && BP_REPAIR_BUDGET=1200 nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/repair_stale_quotes.py >> /var/log/bp-quote-repair.log 2>&1
# 每周日 04:00 刷新基金全字段（平安业绩 + 天天基金费率）
0 4 * * 0 root cd /opt/balanced-portfolio && nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_fund_data.py --all >> /var/log/bp-fund-backfill.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-data-health
cat /etc/cron.d/bp-data-health
echo "=== 刷新健康表（记录 + 极值） ==="
BP_HEALTH_REPAIR_LIMIT=0 timeout 600 .venv/bin/python scripts/quote_coverage_watch.py 2>&1 | grep -aE "expected|health|extremes" | tail -4
su - postgres -c "psql -d postgres -tAc \"select status, count(*) from bp_index_quote_health group by 1 order by 2 desc\""
