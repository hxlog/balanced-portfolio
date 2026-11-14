#!/usr/bin/env bash
echo "--- pm2 status ---"
pm2 list --no-color 2>/dev/null | grep -E "bp-api|bp-web" || true
echo "--- bp-api errors ---"
tail -20 /root/.pm2/logs/bp-api-error.log 2>/dev/null