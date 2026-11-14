#!/usr/bin/env bash
set -euo pipefail
cd /opt/balanced-portfolio
git apply --check /tmp/p2.patch
git apply --index /tmp/p2.patch
git -c user.name=deploy -c user.email=deploy@local commit -qm "P2: 对外 API token 与 /api/v1"
pm2 restart bp-api >/dev/null
sleep 4
echo "--- smoke ---"
curl -s -o /dev/null -w "no-auth:%{http_code}\n" "http://127.0.0.1:8000/api/v1/market/daily?codes=000300&start=2026-11-01&end=2026-11-14"
curl -s -o /dev/null -w "admin-list:%{http_code}\n" "http://127.0.0.1:8000/api/admin/api-tokens"