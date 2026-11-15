#!/usr/bin/env bash
echo "--- 日志中 global 相关 ---"
grep -aE "标普|道琼斯|恒生|纳斯达克|费城|targets" /tmp/xueqiu_backfill3.log | head -8
echo "--- 缺失 symbol 中的 global 名称 ---"
cd /opt/balanced-portfolio
su - postgres -c "psql -d postgres -tAc \"select c.symbol from bp_index_config c where c.is_deleted = 0 and c.category = chr(105)||chr(110)||chr(100)||chr(101)||chr(120) and c.index_code is not null and not exists (select 1 from bp_index_quote_daily q where q.symbol = c.symbol and q.adjust = chr(98)||chr(102)||chr(113))\"" | head -40