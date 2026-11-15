#!/usr/bin/env bash
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) Mobile/15E148"
curl -s --max-time 20 -A "$UA" "https://pacdn.m.stock.pingan.com/omm/phonex/lib/loader.js?v=20261029185719" -o /tmp/loader.js
echo "loader bytes: $(wc -c < /tmp/loader.js)"
head -c 800 /tmp/loader.js
echo
echo "--- js 引用 ---"
grep -oE "[a-zA-Z0-9_/.-]+\.js" /tmp/loader.js | sort -u | head -12