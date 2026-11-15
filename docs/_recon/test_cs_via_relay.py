# -*- coding: utf-8 -*-
"""测试：经 SG relay 访问中证官网 API（3 个 symbol）。"""
import os, sys, time
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:10809"
os.environ["HTTP_PROXY"] = "http://127.0.0.1:10809"
os.environ["NO_PROXY"] = "127.0.0.1,localhost,81.71.158.239"
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.http_session import install_hardened_session
install_hardened_session()
import requests
API = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
for code in ("930641", "931000", "H30007"):
    t0 = time.time()
    try:
        r = requests.get(API, params={"indexCode": code, "startDate": "20250101", "endDate": "20261114"}, timeout=40, headers={"Referer": "https://www.csindex.com.cn/", "User-Agent": "Mozilla/5.0 Chrome/120"})
        rows = (r.json().get("data") or []) if r.status_code == 200 else []
        print(code, "status", r.status_code, "rows", len(rows), "took", round(time.time()-t0, 1))
    except Exception as exc:
        print(code, "FAIL", type(exc).__name__, str(exc)[:100], round(time.time()-t0, 1))
    time.sleep(1)
