#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
rm -rf web/app/assets
git add -A web bp_api || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "dashboard: 与 builder 共用四象限/一篮子资产切换，移除独立篮子区块；资产池并入 /admin/assets 并限制资产编辑权限" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
pm2 restart bp-api >/dev/null
sleep 6
for p in /dashboard "/dashboard?mode=basket" /admin/assets /builder?mode=basket; do curl -s -o /dev/null -w "$p -> %{http_code}\n" --max-time 40 "http://127.0.0.1:3000$p"; done
echo "=== 旧 /assets ==="
curl -s -o /dev/null -w "/assets -> %{http_code}\n" --max-time 20 "http://127.0.0.1:3000/assets"
echo "=== 未授权 API ==="
curl -s -o /dev/null -w "unified anonymous -> %{http_code}\n" --max-time 20 "http://127.0.0.1:8000/api/assets/unified?limit=1"
