#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web bp_api ddl docs || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(basket): /dashboard 篮子组合区块（打开/复制/删除）、保存篮子对话框、回测日期区间；API Jsonb 修复" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -4
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "dashboard:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/dashboard"
curl -s -o /dev/null -w "builder:%{http_code}\n" --max-time 40 "http://127.0.0.1:3000/builder?mode=basket"
