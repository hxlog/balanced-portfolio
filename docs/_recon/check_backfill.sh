#!/usr/bin/env bash
echo '--- backfill log tail ---'
tail -4 /tmp/valuation_backfill.log 2>/dev/null
echo '--- progress: configs with data ---'
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_index_quote_daily where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
echo '--- clean coverage ---'
su - postgres -c "psql -d postgres -tAc \"select count(distinct symbol) from bp_quote_clean where adjust = 'bfq' and symbol in (select index_code from bp_index_master where is_tracked)\""
date