#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web bp_api ddl || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(basket): 等权净值线/调仓标记与权重变化弹窗、保存篮子、回测日期区间" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -4
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "builder:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/builder?mode=basket"
