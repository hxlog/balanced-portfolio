"""再探：同花顺多市场代码格式 + 中证官网 WAF 预热。"""
import sys, time, requests
sys.stdout.reconfigure(encoding="utf-8")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
H = {"User-Agent": UA}

def probe(name, url, headers=None, timeout=10):
    try:
        r = requests.get(url, headers=headers or H, timeout=timeout)
        body = (r.text or "").strip()
        print(f"{name}: {r.status_code} len={len(body)} :: {body[:100]}")
    except Exception as exc:
        print(f"{name}: FAIL {type(exc).__name__} {str(exc)[:60]}")

code = "930782"
for fmt in (f"zs_{code}", f"zs_1A0001", f"1A0001", f"48_{code}", f"zs_H30269"):
    probe("10jqka-" + fmt, f"http://d.10jqka.com.cn/v6/line/{fmt}/01/last.js")

print("--- CSIndex 预热 ---")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9"})
try:
    home = s.get("https://www.csindex.com.cn/", timeout=15)
    print("home:", home.status_code, "len", len(home.text or ""), "cookies", list(s.cookies.keys())[:5])
except Exception as exc:
    print("home FAIL", type(exc).__name__)
try:
    r = s.get("https://www.csindex.com.cn/csindex-home/perf/index-perf",
              params={"indexCode": code, "startDate": "20261001", "endDate": "20261115"},
              headers={"Referer": "https://www.csindex.com.cn/", "X-Requested-With": "XMLHttpRequest"}, timeout=15)
    body = r.text or ""
    print("perf:", r.status_code, "len", len(body), body[:120])
except Exception as exc:
    print("perf FAIL", type(exc).__name__, str(exc)[:80])