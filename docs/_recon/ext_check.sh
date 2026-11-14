#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- external ---"
curl -s -o /dev/null -w "home:%{http_code} " https://xushilu.com/
curl -s -o /dev/null -w "valuation:%{http_code}\n" https://xushilu.com/valuation
curl -s https://xushilu.com/valuation | grep -oE "(上证指数|示例数据)" | sort | uniq -c