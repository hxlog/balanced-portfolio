#!/usr/bin/env bash
for code in 930957 930641 931000 000300 399006; do
  out=$(curl -s -o /tmp/cs_$code.json -w "%{http_code}" --max-time 15 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=$code&startDate=20250101&endDate=20261114")
  size=$(wc -c < /tmp/cs_$code.json)
  echo "$code -> http=$out size=$size"
done