#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
git add -A web bp_api || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(web): 详情页 F9 级工作台（指标x窗口x分位/σ联动、成分披露、简介、收益风险、分位矩阵、行业分布、跟踪基金）" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -4
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "detail:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/valuation/000300"
