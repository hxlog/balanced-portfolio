#!/usr/bin/env bash
cd /opt/balanced-portfolio
git add -A bp_api/quant/basket.py || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "P4: 补充 quant 篮子引擎" || true
pm2 restart bp-api >/dev/null
sleep 5
echo "--- health ---"
curl -s -o /dev/null -w "api-health:%{http_code}\n" http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "basket:%{http_code}\n" -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:8000/api/basket/optimize
echo "--- web ---"
curl -s -o /dev/null -w "valuation:%{http_code}\n" http://127.0.0.1:3000/valuation