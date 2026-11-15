import sys, json, requests
sys.stdout.reconfigure(encoding="utf-8")
H = {"User-Agent": "Mozilla/5.0 Chrome/120", "Referer": "https://www.csindex.com.cn/"}
for code in ("000905", "930719", "H30269"):
    r = requests.get("https://www.csindex.com.cn/csindex-home/perf/index-perf",
                     params={"indexCode": code, "startDate": "20261001", "endDate": "20261115"}, headers=H, timeout=15)
    rows = (r.json().get("data") or []) if r.status_code == 200 else []
    print(code, r.status_code, "rows", len(rows), "last3:", [row.get("tradeDate") for row in rows[-3:]])
print("--- sina 000300 ---")
r = requests.get("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                 params={"symbol": "sh000300", "scale": "240", "ma": "no", "datalen": "4"},
                 headers={"User-Agent": "Mozilla/5.0 Chrome/120", "Referer": "https://finance.sina.com.cn/"}, timeout=15)
data = r.json() if r.status_code == 200 else []
print("sina:", r.status_code, [row.get("day") for row in (data or [])])
print("--- 平安快照日期（对照真实交易日） ---")
from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select max(trade_date) from bp_index_valuation_daily where is_primary")
    print("valuation latest:", cur.fetchone()[0])
    cur.execute("select cal_date, is_trading from bp_trading_calendar where market=%s and cal_date between current_date - 6 and current_date order by cal_date", ("CN",))
    print([(str(r[0]), r[1]) for r in cur.fetchall()])