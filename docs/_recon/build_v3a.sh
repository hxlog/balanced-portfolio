#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web scripts docs || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(valuation): 区块级无闪切换（客户端缓存取数+保留旧图+进度条）、红利图回归/自适应轴、矩阵窗口标注、1600px、MVI 研究脚本与报告" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -4
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "valuation:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/valuation"
curl -s -o /dev/null -w "valuation-1y:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/valuation?window=1y&metric=pb"
