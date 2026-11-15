"""诊断：雪球增量任务为何只更新到 11-13 的部分指数 + 修复抓取测试。"""
import sys, json, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import requests
from bp_ingest.http_session import install_hardened_session

install_hardened_session()

def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"})
    s.get("https://xueqiu.com/about", timeout=20)
    s.headers.update({"Referer": "https://xueqiu.com/"})
    return s

def fetch(session, xq_symbol, count=-10):
    r = session.get("https://stock.xueqiu.com/v5/stock/chart/kline.json", params={
        "symbol": xq_symbol, "begin": str(int(time.time()*1000)), "period": "day",
        "type": "before", "count": str(count), "indicator": "kline"}, timeout=30)
    if r.status_code != 200:
        return ("http " + str(r.status_code), [])
    data = (r.json().get("data") or {})
    items = data.get("item") or []
    return ("ok", items)

session = make_session()
from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("""
        select h.symbol, h.last_trade_date, m.name from bp_index_quote_health h
        join bp_index_master m on m.index_code = h.symbol
        where h.status in ('stale','dead') order by h.lag_trading_days desc limit 8
    """)
    rows = cur.fetchall()
print("stale samples:", rows)
for symbol, _, name in rows[:4]:
    for candidate in ([f"CSI{symbol}", f"SH{symbol}", f"SZ{symbol}", symbol] if symbol[0].isdigit() else [f"CSI{symbol}", symbol]):
        status, items = fetch(session, candidate)
        print(symbol, name, candidate, status, "items", len(items))
        if items:
            print("   last ts:", items[-1][0], "close:", items[-1][4])
            break
        time.sleep(0.3)