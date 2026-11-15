#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
# 服务器上的 git 只用于记录，不依赖远端
git add -A web || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(web): /valuation 重构版 - 代表性宽基真实分位、PE-Band、行业热力、估值矩阵、多窗口多指标筛选表格" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -8
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "web:%{http_code}\n" --max-time 20 http://127.0.0.1:3000/valuation
