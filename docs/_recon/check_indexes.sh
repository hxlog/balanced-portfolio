#!/usr/bin/env bash
echo '--- bp_quote_clean 索引 ---'
su - postgres -c "psql -d postgres -tAc \"select indexname, indexdef from pg_indexes where tablename = 'bp_quote_clean'\""
echo '--- 表大小 ---'
su - postgres -c "psql -d postgres -tAc \"select relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid)) from pg_stat_user_tables where relname in ('bp_quote_clean','bp_index_valuation_daily','bp_index_percentile')\""