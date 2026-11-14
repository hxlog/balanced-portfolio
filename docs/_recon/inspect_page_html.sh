#!/usr/bin/env bash
cd /opt/balanced-portfolio
curl -s http://127.0.0.1:3000/valuation -o /tmp/val.html
echo "size: $(wc -c < /tmp/val.html)"
echo '--- markers ---'
for m in 'Mock 示例' '正在加载指数估值数据' '上证指数' '中证中药' '沪深300' 'PE (TTM)' 'table'; do printf '%-24s %s\n' "$m" "$(grep -o "$m" /tmp/val.html | wc -l)"; done
echo '--- 上下文 ---'
grep -o 'Mock 示例[^<]*' /tmp/val.html | head -2
grep -o '尚未接入 API[^<]*' /tmp/val.html | head -2