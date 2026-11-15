# -*- coding: utf-8 -*-
"""刷新 bp_asset_coverage 覆盖快照（ETL 完成后运行）。"""
from __future__ import annotations

import os
import sys

import psycopg

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")


def load_env() -> dict:
    values = {}
    path = os.path.join(REPO, ".env")
    if not os.path.exists(path):
        return values
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split(" #")[0].strip().strip('"').strip("'")
    return values


def main() -> int:
    env = load_env()
    conn = psycopg.connect(
        host=os.getenv("BP_ETL_DB_HOST") or "127.0.0.1",
        port=int(env.get("PGPORT", "5432")), dbname=env.get("PGDATABASE", "postgres"),
        user=env.get("PGUSER", "postgres"), password=env.get("PGPASSWORD", ""))
    with conn, conn.cursor() as cur:
        cur.execute("TRUNCATE bp_asset_coverage")
        cur.execute(
            "INSERT INTO bp_asset_coverage (kind, code, adjust, last_date)"
            " SELECT 'stock', symbol, adjust, max(trade_date) FROM bp_stock_quote_daily GROUP BY symbol, adjust")
        stocks = cur.rowcount
        cur.execute(
            "INSERT INTO bp_asset_coverage (kind, code, adjust, last_date)"
            " SELECT 'fund', fund_code, '', max(trade_date) FROM bp_fund_nav_daily GROUP BY fund_code")
        funds = cur.rowcount
        cur.execute(
            "INSERT INTO bp_asset_coverage (kind, code, adjust, last_date)"
            " SELECT 'index', symbol, 'bfq', max(trade_date) FROM bp_index_quote_daily GROUP BY symbol")
        indices = cur.rowcount
        conn.commit()
    print("coverage refreshed stocks=%d funds=%d indices=%d" % (stocks, funds, indices))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
