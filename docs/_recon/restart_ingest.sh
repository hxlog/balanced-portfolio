#!/usr/bin/env bash
cd /opt/balanced-portfolio
pm2 restart bp-ingest >/dev/null
sleep 6
echo "--- scheduler jobs ---"
pm2 logs bp-ingest --lines 120 --nostream 2>/dev/null | grep -iE "crypto-futures|Added job" | tail -12
echo "--- pm2 status ---"
pm2 list --no-color | grep bp-ingest