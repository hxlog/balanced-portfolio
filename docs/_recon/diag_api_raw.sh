#!/usr/bin/env bash
echo "--- api status ---"
pm2 list --no-color | grep bp-api
curl -s -o /dev/null -w "health:%{http_code}\n" --max-time 8 http://127.0.0.1:8000/api/health
echo "--- import check ---"
cd /opt/balanced-portfolio && .venv/bin/python -c "import bp_api.main; print('import ok')" 2>&1 | tail -3
echo "--- error log ---"
tail -12 /root/.pm2/logs/bp-api-error.log 2>/dev/null