#!/usr/bin/env bash
echo '--- running? ---'
pgrep -f 'bp_ingest run' >/dev/null && echo running || echo finished
echo '--- log tail ---'
tail -c 400 /tmp/valuation_backfill.log | tr -d '\r' | tail -3
echo '--- coverage ---'
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
date