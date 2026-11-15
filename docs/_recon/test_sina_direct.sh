#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
for sym in sh000300 sz399006 sh000905 sh000016; do
  curl -s -o /tmp/sina_$sym.json -w "$sym -> %{http_code} %{size_download} %{time_total}s\n" --max-time 15 -A "$UA" "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=$sym&scale=240&ma=no&datalen=5"
done
head -c 260 /tmp/sina_sh000300.json; echo
