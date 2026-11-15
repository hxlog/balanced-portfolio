#!/usr/bin/env bash
cd /tmp
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
curl -s --max-time 20 -A "$UA" "https://m.stock.pingan.com/omm/phonex/indexZone/page/index.html?key=INDEX_F10_H5&type=ZI&code=930641" -o /tmp/pa.html
echo "page bytes: $(wc -c < /tmp/pa.html)"
grep -oE "src=\"[^\"]+\.js[^\"]*\"" /tmp/pa.html | head -10
echo "--- 页面内关键词 ---"
grep -oiE "kline|k线|history|queryIndex" /tmp/pa.html | sort | uniq -c | head