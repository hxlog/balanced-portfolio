#!/usr/bin/env bash
echo "=== 服务器到腾讯行情可达性 ==="
curl -s -o /dev/null -w "tencent:%{http_code} %{time_total}s\n" --max-time 15 "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,5,qfq"
echo "=== 当前行情/净值覆盖 ==="
su - postgres -c "psql -d postgres -tAc \"select adjust, count(distinct symbol), count(*) from bp_stock_quote_daily group by 1\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct fund_code), count(*) from bp_fund_nav_daily\""
