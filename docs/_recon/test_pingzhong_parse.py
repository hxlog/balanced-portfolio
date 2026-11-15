import json, re, sys
sys.stdout.reconfigure(encoding="utf-8")
import requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
      "Referer": "https://fundf10.eastmoney.com/"}
code = "005827"
r = requests.get("https://fund.eastmoney.com/pingzhongdata/" + code + ".js", headers=UA, timeout=25)
text = r.text
m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", text)
print("status", r.status_code, "len", len(text), "match", bool(m))
if m:
    data = json.loads(m.group(1))
    print("rows", len(data), "first", data[0], "last", data[-1])
m2 = re.search(r"Data_ACWorthTrend\s*=\s*(\[.*?\]);", text)
print("acworth", bool(m2), (json.loads(m2.group(1)[:200] if False else m2.group(1))[:2] if m2 else None))
