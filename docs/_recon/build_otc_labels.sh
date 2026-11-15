#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web bp_api scripts ddl docs || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "数据：增量 ETL 脚本（A股 daily/weekly + 基金日增量）与覆盖率报告；OTC 去 Experiment 标签；覆盖率基金口径修正" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "otc:%{http_code}\n" --max-time 40 "http://127.0.0.1:3000/otc-derivatives-pricing"
