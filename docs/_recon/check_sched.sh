#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- scheduler jobs ---"
pm2 logs bp-ingest --lines 200 --nostream 2>/dev/null | grep -iE "valuation|Adding job|scheduler" | tail -8 || echo none