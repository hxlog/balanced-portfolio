#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
NOW=$(date +%s)000
probe() {
  body=$(curl -s -b /tmp/xq3.cookie -A "$UA" -H "Referer: https://xueqiu.com/" --max-time 15 "https://stock.xueqiu.com/v5/stock/chart/kline.json?symbol=$1&begin=$NOW&period=day&type=before&count=-2&indicator=kline")
  n=$(echo "$body" | grep -o '"item"' | wc -l)
  echo "$1 -> $n"
}
for s in ".DAX" ".CAC" ".NIKKEI" ".FTSE" ".KS11" ".AXJO" ".BSESN" ".BVSP" ".STI" ".SOX" "HSTECH" "HKHSTECH" ".TWII"; do probe "$s"; done