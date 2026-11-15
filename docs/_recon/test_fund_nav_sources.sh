#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 510300 是否已有行情 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*), min(trade_date), max(trade_date) from bp_index_quote_daily where symbol='510300'\""
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_index_quote_daily where symbol in ('510300','510310','159919','512100')\""
echo "=== 天天基金净值源测试 ==="
.venv/bin/python - <<'PY'
import requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
for url, name in [
    ("https://fund.eastmoney.com/pingzhongdata/510300.js", "pingzhongdata"),
    ("https://api.fund.eastmoney.com/f10/lsjz?fundCode=510300&pageIndex=1&pageSize=5&startDate=&endDate=", "f10-lsjz"),
]:
    try:
        headers = dict(UA); headers["Referer"] = "https://fundf10.eastmoney.com/"
        r = requests.get(url, headers=headers, timeout=20)
        print(name, r.status_code, len(r.text), r.text[:110].replace("\n", " "))
    except Exception as exc:
        print(name, "FAIL", type(exc).__name__, str(exc)[:80])
PY
