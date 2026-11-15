#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
rm -f web/app/valuation/ValuationHome.tsx
git add -A web bp_api ddl || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(web): /valuation v2 总览（URL+Suspense 切换、Valuation Band、红利指数图、双散点矩阵、默认有基金+规模排序）" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -6
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "valuation:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/valuation"
curl -s -o /dev/null -w "valuation-w1y:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/valuation?window=1y&metric=pb"
