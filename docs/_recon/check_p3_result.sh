#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== clean 重复检查 ==="
su - postgres -c "psql -d postgres -tAc \"select symbol, count(*), count(distinct trade_date) from bp_quote_clean where symbol in ('000001','000858') group by 1\""
echo "=== 三口径一致性（000001 抽样）==="
su - postgres -c "psql -d postgres -tAc \"select adjust, min(trade_date), max(trade_date), count(*) from bp_index_quote_daily where symbol = '000001' and category = 'stock' group by 1 order by 1\""
echo "=== builder 股票搜索 ==="
curl -s --max-time 15 "http://127.0.0.1:8000/api/stocks/search?q=%E8%8C%85%E5%8F%B0" | head -c 300
echo
curl -s --max-time 15 "http://127.0.0.1:8000/api/stocks/search?q=600519" | head -c 300
echo
echo "=== 资产池可选数 ==="
su - postgres -c "psql -d postgres -tAc \"select category, count(*) from bp_index_config where is_deleted = 0 and is_selectable group by 1 order by 1\""
