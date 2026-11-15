#!/usr/bin/env bash
echo "--- proc ---"
pgrep -af server_quote_backfill2 | head -2 || echo "not running"
echo "--- log tail ---"
tail -c 800 /tmp/server_backfill2.log | tr -d "\r" | tail -4
echo "--- writes last 2 min ---"
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_index_quote_daily where updated_at > now() - interval '2 minutes' and adjust = chr(98)||chr(102)||chr(113)\""