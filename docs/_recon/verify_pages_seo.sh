#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- pages ---"
for p in / /valuation /valuation/930641 /crypto /crypto-futures /cffex /dashboard /builder /methodology /otc-pricing; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" --max-time 20 "http://127.0.0.1:3000$p"
done
echo "--- sitemap ---"
curl -s --max-time 20 http://127.0.0.1:3000/sitemap.xml | grep -c "<loc>" || echo 0
curl -s --max-time 20 http://127.0.0.1:3000/sitemap.xml | grep -oE "<loc>[^<]+</loc>" | head -4
echo "--- robots ---"
curl -s --max-time 10 http://127.0.0.1:3000/robots.txt | head -8
echo "--- canonical ---"
curl -s --max-time 20 http://127.0.0.1:3000/valuation | grep -oE 'rel="canonical" href="[^"]+"' | head -2