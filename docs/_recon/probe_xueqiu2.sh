#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
curl -sL -c /tmp/xq2.cookie -A "$UA" --max-time 15 "https://xueqiu.com/about" -o /dev/null -w "about:%{http_code}\n"
grep -c "xq_a_token" /tmp/xq2.cookie 2>/dev/null || echo "no token"
head -3 /tmp/xq2.cookie 2>/dev/null