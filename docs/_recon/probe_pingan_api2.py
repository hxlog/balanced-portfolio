# -*- coding: utf-8 -*-
import requests, json, sys
sys.stdout.reconfigure(encoding="utf-8")
s = requests.Session()
s.headers.update({
 "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1",
 "Referer":"https://m.stock.pingan.com/omm/phonex/page/index.html?key=INDEX_F10_H5&type=ZI&code=930641",
 "Origin":"https://m.stock.pingan.com","X-Requested-With":"XMLHttpRequest"})
base = "https://m.stock.pingan.com/omm/v2/http/mop/vault/query"
codes10 = "ZI930641,ZI931468,ZI930653,ZI930697,ZI931071,ZI931079,SH000300,SH000905,SZ399997,SZ399986"
def q(data, label):
    r = s.post(base, data=data, timeout=30); j = r.json()
    rows = j.get("rows") or []
    print(f"{label}: total={j.get('total')} rows={len(rows)}")
    return rows
rows = q({"key":"INDEX_DATA_V2","codes":codes10,"fields":"code,indexName,peRatio","pageSize":999}, "INDEX_DATA_V2 x10")
print("  codes:", [r.get("code") for r in rows])
rows = q({"key":"S_INDEX_PERFORMANCE","fields":"sInfoWindcode,pctChgRecent1y,stdDev1y","pageSize":999}, "PERF all-paged")
print("  n=", len(rows), "sample:", rows[0] if rows else None)
rows = q({"key":"A_INDEX_VALUATION","fields":"sInfoWind,conNum,mvTotal","pageSize":999}, "VALUATION all-paged")
print("  n=", len(rows))
rows = q({"key":"INDEX_DATA","fields":"code,indexName,peRatio","pageSize":999,"curPage":1}, "INDEX_DATA page1")
print("  n=", len(rows))
# kline endpoint
k = s.post("https://quote.stock.pingan.com/restapi/nodeserver/quote/kLineDate",
           data={"body[code]":"ZI930641","body[kLineType]":"7","body[endDate]":"0","body[count]":"300","body[cqFlag]":"2"}, timeout=30)
print("kline HTTP", k.status_code, "beans=", len(k.json().get("results",{}).get("subBeans",[])))
