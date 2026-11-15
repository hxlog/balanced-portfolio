"""探测 CSI 指数（930782）可用行情通道。"""
import sys, time, json
sys.stdout.reconfigure(encoding="utf-8")
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept": "*/*"}

def probe(name, url, headers=None, timeout=12, check=None):
    t0 = time.time()
    try:
        r = requests.get(url, headers=headers or H, timeout=timeout)
        body = r.text or ""
        sample = body[:110].replace("\n", " ")
        ok = check(body) if check else (r.status_code == 200)
        print(f"{name}: {r.status_code} len={len(body)} ok={ok} {round(time.time()-t0,2)}s :: {sample}")
    except Exception as exc:
        print(f"{name}: FAIL {type(exc).__name__} {str(exc)[:70]} {round(time.time()-t0,2)}s")

code = "930782"
# 1) 同花顺 v6 line
probe("10jqka-zs-v6", f"https://d.10jqka.com.cn/v6/line/zs_{code}/01/last.js", check=lambda b: "'" in b or "[" in b)
probe("10jqka-zs-v4", f"http://d.10jqka.com.cn/v4/line/zs_{code}/01/last.js", check=lambda b: "'" in b or "[" in b)
# 2) 腾讯 gtimg 快照
probe("qq-gtimg", f"https://qt.gtimg.cn/q=sh{code}", check=lambda b: "v_sh" in b)
# 3) 腾讯 ifzq kline
probe("qq-ifzq", f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh{code},day,,,120,qfq", check=lambda b: "data" in b)
# 4) 新浪 jsonp
probe("sina-jsonp", f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService.getKLineData?symbol=sh{code}&scale=240&ma=no&datalen=20", check=lambda b: "day" in b)
# 5) 东财 datacenter
probe("em-datacenter", "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_INDEX_TS_COMPONENT&columns=ALL&pageNumber=1&pageSize=5")
# 6) 中证官网（直连 + 首页预热）
s = requests.Session(); s.headers.update(H)
try:
    s.get("https://www.csindex.com.cn/", timeout=12)
except Exception as exc:
    print("cs-home: FAIL", type(exc).__name__)
probe("cs-indexperf", f"https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode={code}&startDate=20261001&endDate=20261115", check=lambda b: "tradeDate" in b)