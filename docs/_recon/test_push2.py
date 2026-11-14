# -*- coding: utf-8 -*-
import sys, json
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/opt/balanced-portfolio")
from bp_ingest.http_session import install_hardened_session
install_hardened_session()
import requests
URL = "https://push2.eastmoney.com/api/qt/clist/get"
params = {
    "pn": "1", "pz": "50", "po": "1", "np": "1", "fltt": "2", "invt": "2", "fid": "f3",
    "fs": "m:1+t:2",  # 沪市主板
    "fields": "f12,f14,f2,f9,f23,f20",
}
try:
    r = requests.get(URL, params=params, timeout=20)
    print("status", r.status_code, "len", len(r.text))
    j = r.json()
    data = (j.get("data") or {}).get("diff") or []
    print("total:", (j.get("data") or {}).get("total"), "sample:", json.dumps(data[:2], ensure_ascii=False)[:300])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])
