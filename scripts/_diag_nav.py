import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from bp_ingest.config import load_config
from bp_ingest.db import connect
cfg = load_config()
with connect(cfg.db) as conn, conn.cursor() as cur:
    cur.execute("SELECT trade_date, nav FROM bp_fund_nav_daily WHERE fund_code='SH510300' ORDER BY trade_date DESC LIMIT 10")
    print("nav tail:", cur.fetchall())
    cur.execute("SELECT trade_date, close FROM bp_index_quote_daily WHERE symbol='000300' AND adjust='bfq' ORDER BY trade_date DESC LIMIT 10")
    print("idx tail:", cur.fetchall())
    cur.execute("SELECT count(*), count(distinct trade_date) FROM bp_fund_nav_daily WHERE fund_code='SH510300'")
    print("nav rows:", cur.fetchone())
    cur.execute("SELECT trade_date, nav FROM bp_fund_nav_daily WHERE fund_code='SH510300' ORDER BY trade_date DESC LIMIT 3 OFFSET 1")
    print("nav prev:", cur.fetchall())
