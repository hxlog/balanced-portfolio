# -*- coding: utf-8 -*-
"""行情 ETL 端到端验收（只读）：当日四类数据 + 清洗面板 + 管理接口数据源。

用法：
  python scripts/etl_e2e_acceptance.py --date 2026-11-23 --json /tmp/etl-e2e.json
退出码：0=全部达标；1=有未达标项（仍输出明细）。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import date

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8")

EXPECTED = {
    "a_stock": {"bfq_min": 0.985, "hfq_min": 0.985},
    "hk_stock": {"bfq_min": 0.97, "hfq_min": 0.97},
    "etf": {"bfq_min": 0.99, "hfq_min": 0.99},
    "fund_nav": {"min": 0.90},
}
ETL_SOURCES = ("etl_a_stock", "etl_hk_stock", "etl_etf")


def load_env() -> dict:
    env = {}
    path = REPO / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.split(" #")[0].strip().strip('"').strip("'")
    return env


def _ratio(covered: int, total: int) -> float:
    return round(covered / total, 6) if total else 0.0


def evaluate(payload: dict) -> tuple[bool, list[str]]:
    """对汇总 payload 判定是否全部达标；返回 (ok, failures)。"""
    failures: list[str] = []
    for name, rules in EXPECTED.items():
        item = payload["datasets"].get(name, {})
        for adjust, minimum in rules.items():
            covered = item.get(adjust, {}).get("covered", 0) if adjust != "min" else item.get("covered", 0)
            total = item.get(adjust, {}).get("total", 0) if adjust != "min" else item.get("total", 0)
            ratio = _ratio(covered, total)
            if ratio < minimum:
                failures.append(f"{name}:{adjust} 覆盖 {covered}/{total}={ratio:.4f} < {minimum}")
            if not item.get("state_ok_" + (adjust if adjust != "min" else "nav"), False):
                failures.append(f"{name}:{adjust} last_success 未追平")
    return (not failures, failures)


def collect(conn, trade_date: date) -> dict:
    payload: dict = {"trade_date": str(trade_date), "datasets": {}, "clean": {}, "generated_at": None}
    from datetime import datetime, timezone, timedelta

    payload["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    with conn.cursor() as cur:
        def state(name: str, adjust: str) -> bool:
            cur.execute(
                "SELECT last_success_date FROM bp_etl_dataset_state WHERE dataset=%s AND adjust=%s",
                (name, adjust),
            )
            row = cur.fetchone()
            return bool(row and row[0] and row[0] >= trade_date)

        cur.execute(
            "SELECT count(*) FROM bp_stock_quote_daily WHERE trade_date=%s AND adjust='bfq' AND length(symbol)=6",
            (trade_date,),
        )
        a_bfq = int(cur.fetchone()[0])
        cur.execute(
            "SELECT count(*) FROM bp_stock_quote_daily WHERE trade_date=%s AND adjust='hfq' AND length(symbol)=6",
            (trade_date,),
        )
        a_hfq = int(cur.fetchone()[0])
        cur.execute(
            "SELECT count(*) FROM bp_stock_quote_daily WHERE trade_date=%s AND adjust='bfq' AND length(symbol)=5",
            (trade_date,),
        )
        hk_bfq = int(cur.fetchone()[0])
        cur.execute(
            "SELECT count(*) FROM bp_stock_quote_daily WHERE trade_date=%s AND adjust='hfq' AND length(symbol)=5",
            (trade_date,),
        )
        hk_hfq = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM bp_etf_quote_daily WHERE trade_date=%s AND adjust='bfq'", (trade_date,))
        etf_bfq = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM bp_etf_quote_daily WHERE trade_date=%s AND adjust='hfq'", (trade_date,))
        etf_hfq = int(cur.fetchone()[0])
        cur.execute(
            "SELECT count(DISTINCT fund_code) FROM bp_fund_nav_daily WHERE trade_date=%s", (trade_date,)
        )
        fund_cov = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM bp_stock_master WHERE market IN ('SH','SZ','BJ') AND is_delisted=FALSE")
        a_total = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM bp_stock_master WHERE market='HK' AND is_delisted=FALSE")
        hk_total = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM bp_etf_master")
        etf_total = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM bp_fund_master")
        fund_total = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM bp_etl_backlog")
        backlog = int(cur.fetchone()[0])
        cur.execute(
            "SELECT count(DISTINCT (symbol, source)) FROM bp_quote_clean WHERE source = ANY(%s)",
            (list(ETL_SOURCES),),
        )
        clean_etl = int(cur.fetchone()[0])
    payload["datasets"] = {
        "a_stock": {
            "bfq": {"covered": a_bfq, "total": a_total},
            "hfq": {"covered": a_hfq, "total": a_total},
            "state_ok_bfq": state("a_stock", "bfq"),
            "state_ok_hfq": state("a_stock", "hfq"),
            "total": a_total,
        },
        "hk_stock": {
            "bfq": {"covered": hk_bfq, "total": hk_total},
            "hfq": {"covered": hk_hfq, "total": hk_total},
            "state_ok_bfq": state("hk_stock", "bfq"),
            "state_ok_hfq": state("hk_stock", "hfq"),
            "total": hk_total,
        },
        "etf": {
            "bfq": {"covered": etf_bfq, "total": etf_total},
            "hfq": {"covered": etf_hfq, "total": etf_total},
            "state_ok_bfq": state("etf", "bfq"),
            "state_ok_hfq": state("etf", "hfq"),
            "total": etf_total,
        },
        "fund_nav": {
            "covered": fund_cov,
            "total": fund_total,
            "state_ok_nav": state("fund_nav", "nav"),
        },
    }
    payload["backlog"] = backlog
    payload["clean"] = {"etl_assets_with_clean_rows": clean_etl}
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--json", default=None)
    parser.add_argument("--host", default=os.getenv("BP_ETL_DB_HOST") or "81.71.158.239")
    args = parser.parse_args(argv)
    import psycopg

    env = load_env()
    conn = psycopg.connect(
        host=args.host, port=int(env.get("PGPORT", "5432")),
        dbname=env.get("PGDATABASE", "postgres"), user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""),
    )
    try:
        payload = collect(conn, date.fromisoformat(args.date))
    finally:
        conn.close()
    ok, failures = evaluate(payload)
    payload["ok"] = ok
    payload["failures"] = failures
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.json:
        pathlib.Path(args.json).write_text(text, encoding="utf-8")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
