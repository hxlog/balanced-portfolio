import json, sys, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import requests
API = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
proxies = {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}
headers = {"User-Agent": "Mozilla/5.0 Chrome/120", "Referer": "https://www.csindex.com.cn/"}
for code in ("000905", "399006", "930641", "000016", "399986", "H30269", "000985"):
    try:
        r = requests.get(API, params={"indexCode": code, "startDate": "20260101", "endDate": "20261231"},
                         proxies=proxies, timeout=40, headers=headers)
        rows = (r.json().get("data") or []) if r.status_code == 200 else []
        print(code, "status", r.status_code, "rows", len(rows), "last", rows[-1].get("tradeDate") if rows else None)
    except Exception as exc:
        print(code, "FAIL", type(exc).__name__, str(exc)[:80])
    time.sleep(0.5)