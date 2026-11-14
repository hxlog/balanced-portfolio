# -*- coding: utf-8 -*-
import sys, json, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.http_session import install_hardened_session
install_hardened_session()
import requests

def fetch(secid, fqt):
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101", "fqt": str(fqt), "beg": "0", "end": "20500101", "lmt": "100000",
    }
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    d = r.json().get("data") or {}
    return d.get("name"), d.get("klines") or []

for fqt in (0, 2):
    t0 = time.time()
    name, klines = fetch("1.600036", fqt)
    print("fqt", fqt, "name", name, "rows", len(klines), "took", round(time.time()-t0, 2))
    if klines:
        print("  first:", klines[0][:60])
        print("  last :", klines[-1][:60])
