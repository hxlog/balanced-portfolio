#!/usr/bin/env bash
echo "=== tracker fund 表结构 ==="
su - postgres -c "psql -d postgres -c '\d bp_index_tracker_fund'"
echo "=== fund master 表结构 ==="
su - postgres -c "psql -d postgres -c '\d bp_fund_master'"
echo "=== raw 里的 fund 字段样例 ==="
su - postgres -c "psql -d postgres -tAc \"select raw->'etf_fund' from bp_index_valuation_daily where is_primary and index_code='000300' order by trade_date desc limit 1\""
echo
su - postgres -c "psql -d postgres -tAc \"select raw->'otc_fund' from bp_index_valuation_daily where is_primary and index_code='000300' order by trade_date desc limit 1\"" | head -c 600
