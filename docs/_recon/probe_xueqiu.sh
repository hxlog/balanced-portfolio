#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
echo "--- 获取雪球 cookie ---"
curl -s -c /tmp/xq.cookie -A "$UA" --max-time 15 "https://xueqiu.com/" -o /dev/null -w "home:%{http_code}\n"
grep -c "xq_a_token" /tmp/xq.cookie || true
echo "--- K 线测试 ---"
for sym in "SH000300" "SH930641" "CSI930641" "SZ399006"; do
  code=$(curl -s -b /tmp/xq.cookie -A "$UA" --max-time 15 "https://stock.xueqiu.com/v5/stock/chart/kline.json?symbol=$sym&begin=$(date +%s)000&period=day&type=before&count=-5&indicator=kline" | head -c 160)
  echo "$sym -> $code"
done