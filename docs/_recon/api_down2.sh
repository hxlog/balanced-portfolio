#!/usr/bin/env bash
echo "--- bp-api status ---"
pm2 list --no-color 2>/dev/null | grep bp-api || true
echo "--- last error ---"
tail -15 /root/.pm2/logs/bp-api-error.log 2>/dev/null
echo "--- file exists ---"
ls -la /opt/balanced-portfolio/bp_api/quant/basket.py 2>/dev/null || echo missing