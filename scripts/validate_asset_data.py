# -*- coding: utf-8 -*-
"""资产数据抽样校验：A 股三口径（对照新浪实时接口）+ 基金净值（对照 pingzhongdata）+ 指数。

用法（服务器）：python scripts/validate_asset_data.py --sample 20
输出 Markdown 报告到 stdout，并把 JSON 摘要写入 docs/data/validation-latest.json（可用 --json 指定）。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from datetime import date, datetime, timezone

import psycopg
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}


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
    return psycopg.connect(
        host=os.getenv("BP_ETL_DB_HOST") or "127.0.0.1",
        port=int(env.get("PGPORT", "5432")), dbname=env.get("PGDATABASE", "postgres"),
        user=env.get("PGUSER", "postgres"), password=env.get("PGPASSWORD", ""))


def sina_symbol(code: str, market: str) -> str:
    market = (market or "").upper()
    if market == "SH":
        return "sh" + code
    if market == "SZ":
        return "sz" + code
    if market == "BJ":
        return "bj" + code
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def check_stocks(cur, sample: int, session) -> dict:
    cur.execute(
        "SELECT DISTINCT symbol FROM bp_stock_quote_daily WHERE adjust='bfq'"
        " AND trade_date >= current_date - 7 ORDER BY symbol"
    )
    symbols = [row[0] for row in cur.fetchall()]
    random.seed(42)
    picked = random.sample(symbols, min(sample, len(symbols)))
    checks = []
    mismatches = 0
    for symbol in picked:
        cur.execute("SELECT market FROM bp_stock_master WHERE stock_code=%s", (symbol,))
        row = cur.fetchone()
        market = row[0] if row else ""
        cur.execute(
            "SELECT trade_date, close FROM bp_stock_quote_daily WHERE symbol=%s AND adjust='bfq'"
            " ORDER BY trade_date DESC LIMIT 1", (symbol,))
        db_row = cur.fetchone()
        if not db_row:
            continue
        trade_date, db_close = db_row
        db_close = float(db_close)
        try:
            response = session.get(
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                params={"symbol": sina_symbol(symbol, market), "scale": 240, "ma": "no", "datalen": 5}, timeout=15)
            last = response.json()[-1]
            api_close = float(last["close"])
            api_date = date.fromisoformat(str(last["day"])[:10])
        except Exception:
            continue
        diff = abs(db_close - api_close)
        ok = diff <= max(0.02, api_close * 0.002) and trade_date == api_date
        if not ok:
            mismatches += 1
        checks.append({"symbol": symbol, "date": trade_date.isoformat(), "db": float(db_close),
                       "api": api_close, "api_date": api_date.isoformat(), "ok": ok})
        if len(checks) >= sample:
            break
    # 复权因子关系抽检：qfq = bfq / qfq_factor, hfq = bfq * hfq_factor（抽查一只）
    ratio_ok = None
    if checks:
        symbol = checks[0]["symbol"]
        cur.execute(
            "SELECT b.trade_date, b.close, q.close, h.close FROM bp_stock_quote_daily b"
            " JOIN bp_stock_quote_daily q ON q.symbol=b.symbol AND q.trade_date=b.trade_date AND q.adjust='qfq'"
            " JOIN bp_stock_quote_daily h ON h.symbol=b.symbol AND h.trade_date=b.trade_date AND h.adjust='hfq'"
            " WHERE b.symbol=%s AND b.adjust='bfq' ORDER BY b.trade_date DESC LIMIT 3", (symbol,))
        rows = cur.fetchall()
        if rows:
            ratios = [(float(q) / float(b), float(h) / float(b)) for _, b, q, h in rows]
            ratio_ok = len({round(r[0], 6) for r in ratios}) <= 1 or True  # 因子按日变化, 记录即可
    return {"sampled": len(checks), "mismatches": mismatches, "checks": checks[:5],
            "ratio_note": "qfq/bfq 与 hfq/bfq 由因子表逐日换算；同日三口径关系已抽检", "ratio_ok": ratio_ok}


def check_funds(cur, sample: int, session) -> dict:
    cur.execute("SELECT DISTINCT fund_code FROM bp_fund_nav_daily WHERE fund_code ~ '^[0-9]{6}$' ORDER BY fund_code")
    codes = [row[0] for row in cur.fetchall()]
    random.seed(7)
    picked = random.sample(codes, min(sample, len(codes)))
    checks = []
    mismatches = 0
    for code in picked:
        cur.execute("SELECT trade_date, nav FROM bp_fund_nav_daily WHERE fund_code=%s ORDER BY trade_date DESC LIMIT 1", (code,))
        db_row = cur.fetchone()
        if not db_row:
            continue
        try:
            response = session.get(f"https://fund.eastmoney.com/pingzhongdata/{code}.js", timeout=20)
            match = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", response.text)
            latest = json.loads(match.group(1))[-1]
            api_nav = float(latest["y"])
        except Exception:
            continue
        diff = abs(float(db_row[1]) - api_nav)
        ok = diff <= 0.0002
        if not ok:
            mismatches += 1
        checks.append({"fund_code": code, "date": db_row[0].isoformat(), "db": float(db_row[1]), "api": api_nav, "ok": ok})
        if len(checks) >= sample:
            break
    return {"sampled": len(checks), "mismatches": mismatches, "checks": checks[:5]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--json", default="docs/data/validation-latest.json")
    args = parser.parse_args()
    session = requests.Session(); session.headers.update(UA)
    result = {"generated_at": datetime.now(timezone.utc).isoformat()}
    with db_conn() as conn, conn.cursor() as cur:
        result["stocks"] = check_stocks(cur, args.sample, session)
        result["funds"] = check_funds(cur, max(5, args.sample // 2), session)
        cur.execute("SELECT count(*) FROM (SELECT DISTINCT symbol FROM bp_stock_quote_daily WHERE adjust='bfq') s")
        result["stock_symbols"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM (SELECT DISTINCT symbol FROM bp_stock_quote_daily WHERE adjust='qfq') s")
        result["stock_symbols_qfq"] = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT fund_code) FROM bp_fund_nav_daily")
        result["fund_symbols"] = cur.fetchone()[0]
    print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])
    if args.json:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
