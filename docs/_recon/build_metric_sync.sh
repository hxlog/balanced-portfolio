#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "fix(web): 指标切换自动显示对应分位列；表格位置条去掉 0/100 刻度" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "valuation:%{http_code}\n" --max-time 40 http://127.0.0.1:3000/valuation
