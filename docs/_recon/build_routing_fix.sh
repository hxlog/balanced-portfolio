#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "fix(routing): builder 模式切换改用 Link、页面壳不再等待资产接口；dashboard 篮子区块置顶并加超时/重试；serverFetch 10s 超时" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -4
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "builder:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/builder?mode=basket"
curl -s -o /dev/null -w "dashboard:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/dashboard"
