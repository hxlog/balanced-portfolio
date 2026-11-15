#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web bp_api ddl scripts docs || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(mvi): 市场估值指数落库+每日刷新+API+双仪表盘面板（估值分/风险分/因子贡献/历史走势）" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -4
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "valuation:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/valuation"
