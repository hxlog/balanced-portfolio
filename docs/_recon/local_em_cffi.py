# -*- coding: utf-8 -*-
"""本机用 curl_cffi 直连东财测试（排除 TLS 指纹问题）。"""
import os, sys
for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy"):
    os.environ.pop(k, None)
sys.stdout.reconfigure(encoding="utf-8")
try:
    from curl_cffi import requests as cffi_requests
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0&beg=20240101&end=20240110"
    r = cffi_requests.get(url, impersonate="chrome120", timeout=25)
    print("status:", r.status_code, "len:", len(r.text), "head:", r.text[:120])
except Exception as exc:
    print("FAIL", type(exc).__name__, str(exc)[:200])
