# -*- coding: utf-8 -*-
"""探测估值指数在现有行情源下的可获取性（抽样）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from datetime import date, timedelta
from bp_ingest.config import load_config
from bp_ingest.db import connect
from bp_ingest.http_session import install_hardened_session
from bp_ingest.sources import fetch_with_fallback

install_hardened_session()
app = load_config()
today = date.today()
start = today - timedelta(days=30)
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select index_code, name, market from bp_index_master where is_tracked order by random() limit 12")
    samples = cur.fetchall()
for code, name, market in samples:
    for source in ("cn_index_em", "hk_index_em", "global_index_em"):
        try:
            df = fetch_with_fallback(source, code, start, today, {})
            if len(df) > 0:
                print(f"OK  {code} {market} {name[:8]} -> {source} rows={len(df)} last={df.trade_date.max()}")
                break
        except Exception as exc:
            pass
    else:
        print(f"FAIL {code} {market} {name[:10]}")
