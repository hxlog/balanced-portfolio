#!/usr/bin/env bash
echo "=== 1) 估值数据完整性 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*) as indices, max(trade_date) from bp_index_valuation_daily where is_primary\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct index_code) from bp_index_valuation_daily where is_primary and trade_date = (select max(trade_date) from bp_index_valuation_daily)\""
echo "=== 2) 全市场估值 ==="
su - postgres -c "psql -d postgres -tAc \"select board, trade_date, pe_median, pct_pe from bp_market_valuation_daily order by trade_date desc limit 5\""
echo "=== 3) 加密快照 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "=== 4) 成分/基金 ==="
su - postgres -c "psql -d postgres -tAc \"select (select count(*) from bp_index_constituent) || chr(47) || (select count(*) from bp_index_fund_master) || chr(47) || (select count(*) from bp_index_tracker_fund)\""
echo "=== 5) 个股 ==="
su - postgres -c "psql -d postgres -tAc \"select symbol, adjust, count(*), max(trade_date) from bp_index_quote_daily where source = @stock_sina@ group by 1,2 order by 1,2 limit 6\"" 2>/dev/null || true
su - postgres -c "psql -d postgres -tAc \"select adjust, count(*), max(trade_date) from bp_index_quote_daily where source like \"stock_%\" group by 1\""
echo "=== 6) 调度器今日任务 ==="
grep -a -E "估值抓取完成|全市场估值快照完成|中证官网口径同步|加密合约采集完成" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -8
echo "=== 7) cron 采集 ==="
tail -2 /var/log/bp-crypto-futures.log 2>/dev/null