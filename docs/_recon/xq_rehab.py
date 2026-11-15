import sys, json, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import requests
from bp_ingest.http_session import install_hardened_session
install_hardened_session()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9"})
r = s.get("https://xueqiu.com/", timeout=20, allow_redirects=True)
print("home:", r.status_code, "len", len(r.text), "cookies", list(s.cookies.keys())[:6])
r2 = s.get("https://stock.xueqiu.com/v5/stock/chart/kline.json", params={
    "symbol": "CSI930782", "begin": str(int(time.time()*1000)), "period": "day",
    "type": "before", "count": "-10", "indicator": "kline"}, timeout=20, headers={"Referer": "https://xueqiu.com/"})
print("kline:", r2.status_code, r2.text[:160])