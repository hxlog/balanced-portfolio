#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 重启并行净值回填 ==="
pkill -f backfill_fund_nav || true
sleep 1
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_fund_nav.py --workers 10 > /tmp/fund_nav_backfill2.log 2>&1 < /dev/null &
echo launched
echo "=== 前端构建 ==="
git add -A web scripts bp_api ddl || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(detail): 成分股排名第一列、基金表风险指标+对比、描述统计模块；基金净值/风险数据管线" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "detail:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/valuation/000300"
