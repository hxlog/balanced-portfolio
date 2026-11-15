#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- sitemap ---"
curl -s --max-time 20 http://127.0.0.1:3000/sitemap.xml | head -c 600
echo
echo "--- sitemap urls ---"
curl -s --max-time 20 http://127.0.0.1:3000/sitemap.xml | grep -oE "<loc>[^<]+</loc>" | head -20
echo "--- valuation page SEO ---"
curl -s --max-time 20 http://127.0.0.1:3000/valuation | grep -oE '<title>[^<]*</title>|property="og:[a-z:]+"|application/ld\+json|rel="canonical"[^>]*' | head -12
echo "--- detail page SEO ---"
curl -s --max-time 20 http://127.0.0.1:3000/valuation/930641 | grep -oE '<title>[^<]*</title>|property="og:[a-z:]+"|application/ld\+json|rel="canonical"[^>]*' | head -12
echo "--- crypto-futures SEO ---"
curl -s --max-time 20 http://127.0.0.1:3000/crypto-futures | grep -oE '<title>[^<]*</title>|property="og:[a-z:]+"|application/ld\+json' | head -10