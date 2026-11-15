#!/usr/bin/env bash
echo "--- procs ---"
pgrep -fc server_quote_backfill || echo 0
pgrep -fc server_clean_indexes || echo 0
echo "--- backfill progress ---"
grep -a "progress" /tmp/server_backfill.log | tail -3
tail -2 /tmp/server_backfill.log | tr -d "\r" | tail -1
echo "--- clean ---"
tail -2 /tmp/server_clean.log
echo "--- mem ---"
free -h | head -2
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = chr(98)||chr(102)||chr(113)\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = chr(98)||chr(102)||chr(113)\""
echo "--- health ---"
curl -s -o /dev/null -w "api:%{http_code} " --max-time 8 http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "web:%{http_code}\n" --max-time 8 http://127.0.0.1:3000/valuation
date