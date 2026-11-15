#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
NOW=$(date +%s)000
probe() {
  body=$(curl -s -b /tmp/xq2.cookie -A "$UA" -H "Referer: https://xueqiu.com/" --max-time 15 "https://stock.xueqiu.com/v5/stock/chart/kline.json?symbol=$1&begin=$NOW&period=day&type=before&count=-2&indicator=kline")
  n=$(echo "$body" | grep -o '"item"' | wc -l)
  echo "$1 -> $n items | $(echo "$body" | head -c 90)"
}
for s in "CSI931000" "SH000009" "CSI970083" "CSI950180" "H30007" "CSIH30007" "SH000015" "CSI980017"; do probe "$s"; done