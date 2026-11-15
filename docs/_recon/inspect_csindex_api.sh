#!/usr/bin/env bash
cd /tmp
curl -s -o /tmp/cs1.json --max-time 20 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=930641&startDate=20260101&endDate=20261114"
python3 - <<PY
import json
d = json.load(open("/tmp/cs1.json"))
rows = d.get("data") or []
print("rows:", len(rows))
if rows:
    print("keys:", list(rows[0].keys()))
    print("first:", json.dumps(rows[0], ensure_ascii=False)[:400])
    print("last :", json.dumps(rows[-1], ensure_ascii=False)[:300])
PY
echo "--- 长区间测试 ---"
curl -s -o /tmp/cs2.json --max-time 25 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=930641&startDate=20170101&endDate=20261114"
python3 -c "import json; d=json.load(open('/tmp/cs2.json')); r=d.get('data') or []; print('long rows:', len(r)); print('first date:', r[0]['tradeDate'] if r else None, 'last:', r[-1]['tradeDate'] if r else None)"