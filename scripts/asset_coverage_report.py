# -*- coding: utf-8 -*-
"""数据完整性/覆盖率报告：A 股三口径、基金净值、指数行情。

用法：python scripts/asset_coverage_report.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

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


def db_conn():
    env = load_env()
    conn = psycopg.connect(host=(os.getenv("BP_ETL_DB_HOST") or "127.0.0.1"),
        port=int(env.get("PGPORT", "5432")), dbname=env.get("PGDATABASE", "postgres"),
        user=env.get("PGUSER", "postgres"), password=env.get("PGPASSWORD", ""))
    return conn


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    today = date.today()
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "stocks": {}, "funds": {}, "indices": {}}
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM bp_stock_master WHERE stock_code ~ '^[0-9]{6}$'")
        total = cur.fetchone()[0]
        for adjust in ("bfq", "qfq", "hfq"):
            cur.execute(
                "SELECT count(DISTINCT symbol), count(*), max(trade_date),"
                " min(trade_date), count(DISTINCT symbol) FILTER (WHERE trade_date >= %s)"
                " FROM bp_stock_quote_daily WHERE adjust = %s",
                (today - timedelta(days=7), adjust),
            )
            symbols, rows, last, first, recent = cur.fetchone()
            result["stocks"][adjust] = {
                "symbols": symbols, "rows": rows,
                "coverage_pct": round(symbols / total * 100, 2) if total else 0,
                "first_date": first.isoformat() if first else None,
                "last_date": last.isoformat() if last else None,
                "symbols_with_7d_data": recent,
            }
        result["stocks"]["universe"] = total
        cur.execute(
            "SELECT count(*) FROM ("
            " SELECT fund_code FROM bp_fund_master WHERE fund_code ~ '^[0-9]{6}$'"
            " UNION SELECT DISTINCT fund_code FROM bp_fund_nav_daily WHERE fund_code ~ '^[0-9]{6}$'"
            ") u"
        )
        fund_total = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT fund_code), count(*), max(trade_date) FROM bp_fund_nav_daily")
        fund_symbols, nav_rows, fund_last = cur.fetchone()
        cur.execute("SELECT count(DISTINCT fund_code) FROM bp_fund_nav_daily WHERE trade_date >= %s", (today - timedelta(days=7),))
        fund_recent = cur.fetchone()[0]
        result["funds"] = {
            "universe": fund_total, "symbols": fund_symbols, "rows": nav_rows,
            "coverage_pct": round(fund_symbols / fund_total * 100, 2) if fund_total else 0,
            "last_date": fund_last.isoformat() if fund_last else None,
            "symbols_with_7d_data": fund_recent,
        }
        cur.execute(
            "SELECT count(*), count(*) FILTER (WHERE q.last_date IS NOT NULL) FROM bp_index_master m"
            " LEFT JOIN (SELECT symbol, max(trade_date) AS last_date FROM bp_index_quote_daily GROUP BY symbol) q"
            " ON q.symbol = m.index_code WHERE m.is_active AND m.is_tracked"
        )
        idx_total, idx_with = cur.fetchone()
        result["indices"] = {"universe": idx_total, "with_quotes": idx_with,
                             "coverage_pct": round(idx_with / idx_total * 100, 2) if idx_total else 0}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
