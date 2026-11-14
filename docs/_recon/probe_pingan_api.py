# -*- coding: utf-8 -*-
import requests, json
s = requests.Session()
s.headers.update({
 "User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1",
 "Referer":"https://m.stock.pingan.com/omm/phonex/page/index.html?key=INDEX_F10_H5&type=ZI&code=930641",
 "Origin":"https://m.stock.pingan.com",
 "X-Requested-With":"XMLHttpRequest",
})
base = "https://m.stock.pingan.com/omm/v2/http/mop/vault/query"
def q(data, label):
    try:
        r = s.post(base, data=data, timeout=30)
        j = r.json()
        rows = j.get("rows") or []
        print(f"{label}: HTTP {r.status_code} total={j.get('total')} rows={len(rows)}")
        if rows: print("  sample:", json.dumps(rows[0], ensure_ascii=False)[:260])
        return rows
    except Exception as e:
        print(label, "FAIL", type(e).__name__, str(e)[:160])
q({"key":"INDEX_DATA_V2","codes":"ZI930641,ZI931468,ZI000300","fields":"code,indexName,peRatio,pePercen,pbRatio,dividendRate","pageSize":999}, "batch3")
q({"key":"INDEX_DATA_V2","codes":"ZI930641,ZI931468","fields":"code,indexName,peRatio","pageSize":999}, "batch2")
q({"key":"A_INDEX_DESCRIPTION","fields":"sInfoWindCode,sInfoCompany","pageSize":5}, "desc-paged")
q({"key":"BOND10_TREND","fields":"tradeDt,bAnalyield","pageSize":3,"orderBy":"tradeDt","orderType":"desc"}, "bond-recent")
