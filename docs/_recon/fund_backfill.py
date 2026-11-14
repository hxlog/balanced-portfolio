# -*- coding: utf-8 -*-
"""轻量补齐：只抓跟踪基金并落库（不重跑全量估值）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from datetime import date
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest.valuation_pingan import fetch_tracker_funds
from bp_ingest.valuation_ingest import _build_fund_rows
from bp_api.repositories_valuation import upsert_fund_master, upsert_tracker_funds

def main():
    setup_logging()
    app = load_config()
    with connect(app.db) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("""
                SELECT index_code, COALESCE(raw->'etf_fund', '[]'::jsonb)
                FROM bp_index_valuation_daily WHERE is_primary
            """)
            merged = {code: {"etf_fund": [str(x) for x in (funds or [])]} for code, funds in cur.fetchall()}
            cur.execute("SELECT max(trade_date) FROM bp_index_valuation_daily WHERE is_primary")
            trade_date = cur.fetchone()[0] or date.today()
        codes = sorted({c for v in merged.values() for c in v["etf_fund"]})
        print("indices:", len(merged), "fund codes:", len(codes))
        rows = fetch_tracker_funds(codes)
        print("tracker rows:", len(rows))
        master, tracking = _build_fund_rows(merged, rows, trade_date)
        print("fund master:", len(master), "tracking:", len(tracking))
        with conn.cursor() as cur:
            pass
        upsert_fund_master(conn, master)
        upsert_tracker_funds(conn, tracking)
        conn.commit()
        print("done")

main()
