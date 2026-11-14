#!/usr/bin/env bash
cd /opt/balanced-portfolio
git add -A bp_api/schemas.py || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "P4: 篮子入参 schema" || true
echo "--- import check ---"
.venv/bin/python -c "import bp_api.main; print('import ok', len(bp_api.main.app.routes))" 2>&1 | tail -5
pm2 restart bp-api >/dev/null
sleep 5
curl -s -o /dev/null -w "api-health:%{http_code}\n" http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "basket:%{http_code}\n" -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:8000/api/basket/optimize
curl -s -o /dev/null -w "valuation-api:%{http_code}\n" http://127.0.0.1:8000/api/valuation/overview