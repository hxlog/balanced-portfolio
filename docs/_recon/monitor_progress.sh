#!/usr/bin/env bash
echo "--- backfill ---"
grep -a "progress" /tmp/server_backfill.log | tail -2
echo "--- clean ---"
tail -2 /tmp/server_clean.log
echo "--- mem ---"
free -h | head -2
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = chr(98)||chr(102)||chr(113)\""
echo "--- health ---"
curl -s -o /dev/null -w "api:%{http_code} " --max-time 8 http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "web:%{http_code}\n" --max-time 8 http://127.0.0.1:3000/valuation