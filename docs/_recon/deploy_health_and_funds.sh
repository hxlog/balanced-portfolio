#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 启动行情覆盖率看护（后台） ==="
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/quote_coverage_watch.py > /tmp/quote_health.log 2>&1 < /dev/null &
echo launched
echo "=== 安装 cron ==="
cat > /etc/cron.d/bp-data-health <<'EOF'
# 每工作日 17:10 检查指数行情覆盖率（落后自动补拉），并刷新极值表
10 17 * * 1-5 root cd /opt/balanced-portfolio && nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/quote_coverage_watch.py >> /var/log/bp-data-health.log 2>&1
# 每周日 04:00 刷新基金全字段（平安业绩 + 天天基金费率）
0 4 * * 0 root cd /opt/balanced-portfolio && nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_fund_data.py --all >> /var/log/bp-fund-backfill.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-data-health
cat /etc/cron.d/bp-data-health
echo "=== 构建前端 ==="
git add -A web bp_api ddl scripts || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: 基金全字段+费率回填、行情覆盖率看护、列表数据健康标记、详情基金业绩表" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "valuation:%{http_code} " --max-time 40 http://127.0.0.1:3000/valuation
curl -s -o /dev/null -w "detail:%{http_code}\n" --max-time 40 http://127.0.0.1:3000/valuation/000300
