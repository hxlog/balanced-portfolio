#!/usr/bin/env bash
tail -40 /root/.pm2/logs/bp-api-error.log | grep -B2 -A8 "assets" | tail -25
echo "=== stock master cols ==="
su - postgres -c "psql -d postgres -tAc \"select column_name from information_schema.columns where table_name='bp_stock_master' order by ordinal_position\""
