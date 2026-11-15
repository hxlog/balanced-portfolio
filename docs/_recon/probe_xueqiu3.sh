#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
NOW=$(date +%s)000
for sym in "SH000300" "SH930641" "CSI930641" "SH000905" "SZ399006" "SH931000"; do
  body=$(curl -s -b /tmp/xq2.cookie -A "$UA" -H "Referer: https://xueqiu.com/" --max-time 15 "https://stock.xueqiu.com/v5/stock/chart/kline.json?symbol=$sym&begin=$NOW&period=day&type=before&count=-3&indicator=kline")
  echo "$sym -> $(echo "$body" | head -c 150)"
done