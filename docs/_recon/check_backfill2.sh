#!/usr/bin/env bash
echo '--- backfill log tail ---'
tail -3 /tmp/valuation_backfill.log
echo '--- raw coverage ---'
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
echo '--- clean coverage ---'
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
echo '--- process alive ---'
pgrep -f 'bp_ingest run' > /dev/null && echo yes || echo no
date