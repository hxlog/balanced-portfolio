# -*- coding: utf-8 -*-
import requests, json
from requests.adapters import HTTPAdapter
s = requests.Session()
s.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"})
def head(u):
    try:
        r = s.head(u, timeout=20, allow_redirects=True)
        print("HEAD", r.status_code, r.headers.get("content-length"), r.headers.get("last-modified"), u[:120])
    except Exception as e:
        print("HEAD FAIL", type(e).__name__, str(e)[:120], u[:120])
for code in ["000300","930641"]:
    head(f"https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{code}indicator.xls")
cands = [
 ("POST","https://www.csindex.com.cn/csindex-home/index/indexInfoValue", {"indexCode":"000300","startDate":"2024-01-01","endDate":"2024-12-31"}),
 ("POST","https://www.csindex.com.cn/csindex-home/index/index-value", {"indexCode":"000300","startDate":"2024-01-01","endDate":"2024-12-31"}),
 ("POST","https://www.csindex.com.cn/csindex-home/perf/index-perf", {"indexCode":"000300","startDate":"2024-01-01","endDate":"2024-12-31"}),
]
for m,u,body in cands:
    try:
        r = s.post(u, json=body, timeout=25)
        print(m,u,r.status_code, r.text[:300].replace("\n"," "))
    except Exception as e:
        print(m,u,"FAIL",type(e).__name__,str(e)[:120])
