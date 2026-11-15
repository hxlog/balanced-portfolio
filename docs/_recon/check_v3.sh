#!/usr/bin/env bash
grep -a "progress\|done" /tmp/server_backfill3.log | tail -3
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
free -h | head -2
date