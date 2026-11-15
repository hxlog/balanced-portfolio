#!/usr/bin/env bash
base="https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile"
for code in 931000 H30007 000009 931775 930903 H11146; do
  code2=$(curl -s -o /tmp/t.bin -w "%{http_code}" --max-time 12 "$base/perf/${code}perf.xls")
  size=$(wc -c < /tmp/t.bin)
  echo "$code -> $code2 bytes=$size"
done