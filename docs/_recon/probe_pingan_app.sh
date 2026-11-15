#!/usr/bin/env bash
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) Mobile/15E148"
base="https://pacdn.m.stock.pingan.com/omm/phonex"
for f in "js/_app.js" "js/req.js" "lib/Chart.js"; do
  out="/tmp/$(echo $f | tr "/" "_")"
  code=$(curl -s -o "$out" -w "%{http_code}" --max-time 20 -A "$UA" "$base/$f?v=20261029185719")
  echo "$f -> $code bytes=$(wc -c < $out)"
done
echo "--- _app.js 中的接口 ---"
grep -oE "/omm/phonex/[a-zA-Z0-9_/]+" /tmp/js__app.js 2>/dev/null | sort -u | head -20
echo "--- kline/trend 关键词 ---"
grep -oiE "kline[a-zA-Z]*|trend[a-zA-Z]*|queryIndex[a-zA-Z]*" /tmp/js__app.js 2>/dev/null | sort | uniq -c | sort -rn | head -10