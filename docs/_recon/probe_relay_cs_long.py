import sys, time
sys.stdout.reconfigure(encoding="utf-8")
import requests
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Referer": "https://www.csindex.com.cn/", "Accept": "application/json, text/plain, */*"}
proxies = {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}
for timeout in (60, 120):
    t0 = time.time()
    try:
        r = requests.get(
            "https://www.csindex.com.cn/csindex-home/perf/index-perf",
            params={"indexCode": "930782", "startDate": "20261001", "endDate": "20261115"},
            headers=H, proxies=proxies, timeout=timeout,
        )
        body = r.text or ""
        print("relay", timeout, "->", r.status_code, "len", len(body), "%.1fs" % (time.time() - t0), body[:80])
        if r.status_code == 200 and "tradeDate" in body:
            break
    except Exception as exc:
        print("relay", timeout, "FAIL", type(exc).__name__, str(exc)[:80], "%.1fs" % (time.time() - t0))
