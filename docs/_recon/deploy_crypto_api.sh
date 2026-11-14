#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "--- import check ---"
.venv/bin/python -c "import bp_api.main; print('ok', len(bp_api.main.app.routes))" 2>&1 | tail -3
pm2 restart bp-api >/dev/null
sleep 4
echo "--- endpoints ---"
curl -s -o /dev/null -w "contracts:%{http_code}\n" http://127.0.0.1:8000/api/crypto/futures/contracts
curl -s -o /dev/null -w "summary:%{http_code}\n" http://127.0.0.1:8000/api/crypto/futures/summary
curl -s -o /dev/null -w "series:%{http_code}\n" http://127.0.0.1:8000/api/crypto/futures/BTCUSDT/series
echo "--- summary body ---"
curl -s http://127.0.0.1:8000/api/crypto/futures/summary | head -c 300