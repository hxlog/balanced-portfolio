#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web scripts docs || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "前端：全站页面轻量过渡动画、篮子复权口径中文化与 tooltip、OTC 去 Experiment" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
for p in / /builder?mode=basket /otc-derivatives-pricing /assets; do curl -s -o /dev/null -w "$p -> %{http_code}\n" --max-time 40 "http://127.0.0.1:3000$p"; done
