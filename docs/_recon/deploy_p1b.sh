#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/repositories_valuation.py bp_api/valuation.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 详情接口返回成分股与跟踪基金" || true
pm2 restart bp-api >/dev/null
sleep 3
echo "--- detail smoke ---"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/valuation/930641