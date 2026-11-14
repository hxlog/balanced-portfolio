#!/usr/bin/env bash
cd /opt/balanced-portfolio/web
echo "--- built routes ---"
ls .next/server/app/valuation 2>/dev/null || echo "no valuation dir"
echo "--- git ---"
cd /opt/balanced-portfolio && git log --oneline -1
echo "--- restart web ---"
pm2 restart bp-web >/dev/null
sleep 5
curl -s -o /dev/null -w "detail:%{http_code}\n" http://127.0.0.1:3000/valuation/930641