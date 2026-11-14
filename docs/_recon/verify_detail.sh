#!/usr/bin/env bash
echo "--- internal detail markers ---"
curl -s http://127.0.0.1:3000/valuation/930641 | grep -oE "(云南白药|片仔癀|汇添富|中证中药|分位|股息率|风险溢价)" | sort | uniq -c
echo "--- external ---"
curl -s -o /dev/null -w "ext detail:%{http_code}\n" https://xushilu.com/valuation/930641
echo "--- csindex3 ---"
ps aux | grep -c "[r]un_csindex"
tail -1 /tmp/csindex3.log 2>/dev/null || echo no-log