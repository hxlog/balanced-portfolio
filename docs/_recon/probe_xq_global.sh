#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
curl -sL -c /tmp/xq3.cookie -A "$UA" --max-time 15 "https://xueqiu.com/about" -o /dev/null
NOW=$(date +%s)000
probe() {
  body=$(curl -s -b /tmp/xq3.cookie -A "$UA" -H "Referer: https://xueqiu.com/" --max-time 15 "https://stock.xueqiu.com/v5/stock/chart/kline.json?symbol=$1&begin=$NOW&period=day&type=before&count=-2&indicator=kline")
  n=$(echo "$body" | grep -o '"item"' | wc -l)
  echo "$1 -> $n | $(echo "$body" | head -c 70)"
}
for s in ".IXIC" ".NDX" ".INX" ".DJI" ".GDAXI" ".FCHI" ".N225" "HKHSI" ".HSI" "HKHSCEI" ".SPX"; do probe "$s"; done