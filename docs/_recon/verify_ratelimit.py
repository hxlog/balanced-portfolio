# -*- coding: utf-8 -*-
import sys, json, urllib.request, urllib.error, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
from bp_api.api_tokens import create_token

app = load_config()
with connect(app.db) as conn:
    conn.autocommit = False
    _, token = create_token(conn, "ratelimit-check", ["quotes", "valuation", "percentile"], None, None)
    conn.commit()

url = "http://127.0.0.1:8000/api/v1/index/percentile?codes=930641&metrics=pe_ttm&windows=5y"
codes = []
for i in range(62):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            codes.append(resp.status)
    except urllib.error.HTTPError as exc:
        codes.append(exc.code)
        retry = exc.headers.get("Retry-After")
        if exc.code == 429:
            print("first 429 at request", i + 1, "| Retry-After:", retry)
            try:
                print("body:", exc.read().decode()[:200])
            except Exception:
                pass
            break
print("codes summary:", {c: codes.count(c) for c in set(codes)})
