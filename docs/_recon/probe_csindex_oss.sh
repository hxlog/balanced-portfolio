#!/usr/bin/env bash
base="https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile"
for u in "indicator/930641indicator.xls" "perf/930641perf.xls" "closeweight/930641closeweight.xls" "cons/930641cons.xls" "closing/930641closing.xls"; do
  code=$(curl -s -o /tmp/oss_test.bin -w "%{http_code}" --max-time 15 "$base/$u")
  size=$(wc -c < /tmp/oss_test.bin)
  echo "$u -> $code bytes=$size"
done