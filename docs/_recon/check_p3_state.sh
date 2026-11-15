#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 股票三复权数据 ==="
su - postgres -c "psql -d postgres -tAc \"select adjust, count(distinct symbol), count(*) from bp_index_quote_daily where category = chr(115)||chr(116)||chr(111)||chr(99)||chr(107) group by 1 order by 1\""
echo "=== 股票主数据 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_stock_master\""
echo "=== 资产配置里 stock 类 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_index_config where category = chr(115)||chr(116)||chr(111)||chr(99)||chr(107) and is_deleted = 0\""
echo "=== 中证官网口径 ==="
su - postgres -c "psql -d postgres -tAc \"select count(distinct index_code), max(trade_date) from bp_index_csindex_official\"" 2>/dev/null || echo "表不存在"