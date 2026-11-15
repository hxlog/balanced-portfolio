#!/usr/bin/env bash
su - postgres -c "psql -d postgres -P pager=off -c \"
select 'stocks' t, count(*) n from bp_stock_assets
union all select 'funds', count(*) from bp_fund_master
union all select 'fund_perf', count(*) from bp_fund_performance
union all select 'indices_tracked', count(*) from bp_index_master where is_active and is_tracked
union all select 'index_quotes', count(*) from bp_index_quote_daily
union all select 'fund_nav_like', count(*) from (select 1 from information_schema.tables where table_name in ('bp_fund_nav','bp_fund_quote_daily')) t
union all select 'etf_master', count(*) from bp_etf_master\""
echo '=== 表清单（股票/基金/ETF/行情） ==='
su - postgres -c "psql -d postgres -P pager=off -tAc \"select table_name from information_schema.tables where table_schema='public' and (table_name like '%stock%' or table_name like '%fund%' or table_name like '%etf%') order by 1\""
echo '=== 加密快照字段 ==='
su - postgres -c "psql -d postgres -P pager=off -tAc \"select column_name from information_schema.columns where table_name='bp_crypto_futures_snapshot_5m' order by ordinal_position\""
echo '=== 加密合约数量与时间范围 ==='
su - postgres -c "psql -d postgres -P pager=off -c \"select count(distinct contract_code) contracts, min(captured_at)::date first, max(captured_at)::date last, count(*) rows from bp_crypto_futures_snapshot_5m\""
