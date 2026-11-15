#!/usr/bin/env bash
curl -s http://127.0.0.1:3000/valuation -o /tmp/val2.html
echo "bytes: $(wc -c < /tmp/val2.html)"
grep -o '周位置' /tmp/val2.html | head -3
grep -o '52 周[^<"]*' /tmp/val2.html | head -5
echo '--- build id ---'
ls -la /opt/balanced-portfolio/web/.next/BUILD_ID
cat /opt/balanced-portfolio/web/.next/BUILD_ID