#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web bp_api || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "fix(web): Band 图 y 轴纳入分位带/σ 带；测试对齐多窗口与加密回补" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "valuation:%{http_code} " --max-time 40 http://127.0.0.1:3000/valuation
curl -s -o /dev/null -w "detail:%{http_code}\n" --max-time 40 http://127.0.0.1:3000/valuation/000300
