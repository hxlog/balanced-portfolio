"""指数行情覆盖率看护：
1) 对每只跟踪指数计算「最后行情日 vs 最新交易日」的滞后交易日数，写 bp_index_quote_health；
2) 对滞后/死数据且能通过雪球取数的指数自动补拉（每轮上限），消除 191/33/15 类缺口；
3) 统计输出，供 cron 日志与前端数据健康标记使用。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, "/opt/balanced-portfolio")
os.environ.setdefault("BP_XQ_DELAY", "0.4")
sys.stdout.reconfigure(encoding="utf-8")

import requests

from bp_api.repositories_valuation import upsert_quote_health
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import QuoteRow, connect, upsert_quotes
from bp_ingest.http_session import install_hardened_session

SKIP_REPAIR = int(os.getenv("BP_HEALTH_REPAIR_LIMIT", "120"))


def _load_xq_module():
    spec = importlib.util.spec_from_file_location(
        "xueqiu_quote_backfill",
        "/opt/balanced-portfolio/scripts/xueqiu_quote_backfill.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def latest_trading_day(conn) -> date | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(cal_date) FROM bp_trading_calendar"
            " WHERE market = %s AND is_trading AND cal_date <= current_date",
            ("CN",),
        )
        row = cur.fetchone()
        return row[0] if row else None


def trading_days_between(conn, start: date, end: date) -> int:
    if start >= end:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM bp_trading_calendar"
            " WHERE market = %s AND is_trading AND cal_date > %s AND cal_date <= %s",
            ("CN", start, end),
        )
        row = cur.fetchone()
        return int(row[0] or 0)


def fetch_xueqiu_rows(session, xq, symbol: str, days: int = 40):
    """按雪球 v5 K 线补拉近 N 个交易日（count 负数 = 取最近）。"""
    for xq_symbol in xq.candidate_symbols(symbol, ""):
        try:
            payload = session.get(
                xq.KLINE,
                params={
                    "symbol": xq_symbol,
                    "begin": str(int(time.time() * 1000)),
                    "period": "day",
                    "type": "before",
                    "count": str(-max(days, 5)),
                    "indicator": "kline",
                },
                timeout=30,
            )
            if payload.status_code != 200:
                continue
            data = payload.json().get("data") or {}
            columns = data.get("column") or []
            items = data.get("item") or []
            if not items:
                continue
            dicts = [dict(zip(columns, item)) for item in items]
            return xq.to_rows(symbol, dicts)
        except Exception:  # noqa: BLE001
            continue
    return []


def main() -> int:
    setup_logging()
    install_hardened_session()
    app = load_config()
    xq = _load_xq_module()
    session = xq.make_session()

    with connect(app.db) as conn, conn.cursor() as cur:
        expected = latest_trading_day(conn)
        cur.execute(
            "SELECT index_code FROM bp_index_master WHERE is_active AND is_tracked ORDER BY index_code",
        )
        symbols = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT symbol, max(trade_date) FROM bp_index_quote_daily"
            " WHERE adjust = 'bfq' GROUP BY symbol",
        )
        last_dates = {row[0]: row[1] for row in cur.fetchall()}

    print("expected trading day:", expected, "symbols:", len(symbols), flush=True)
    health_rows = []
    stale: list[tuple[str, int]] = []
    for symbol in symbols:
        last = last_dates.get(symbol)
        if last is None:
            status = "missing"
            lag = None
        else:
            with connect(app.db) as conn:
                lag = trading_days_between(conn, last, expected) if expected else 0
            if lag >= 15:
                status = "dead"
            elif lag >= 1:
                status = "stale"
            else:
                status = "ok"
        health_rows.append({
            "symbol": symbol,
            "last_trade_date": last,
            "expected_trade_date": expected,
            "lag_trading_days": lag,
            "has_quote": last is not None,
            "status": status,
        })
        if status in ("stale", "dead"):
            stale.append((symbol, lag or 0))

    with connect(app.db) as conn:
        conn.autocommit = False
        upsert_quote_health(conn, health_rows)
        conn.commit()
    counts: dict[str, int] = {}
    for row in health_rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("health:", counts, flush=True)

    # 自动补拉：先修滞后最严重的，限制每轮数量，避免再次打爆数据源。
    repaired = 0
    stale.sort(key=lambda item: -item[1])
    for symbol, lag in stale[:SKIP_REPAIR]:
        try:
            rows = fetch_xueqiu_rows(session, xq, symbol, days=max(30, min(lag + 5, 120)))
        except Exception as exc:  # noqa: BLE001
            print("repair fail", symbol, type(exc).__name__, str(exc)[:80], flush=True)
            continue
        if not rows:
            continue
        try:
            with connect(app.db) as conn:
                conn.autocommit = False
                upsert_quotes(conn, rows)
                conn.commit()
            repaired += 1
            print("repaired", symbol, "lag", lag, "rows", len(rows), flush=True)
        except Exception as exc:  # noqa: BLE001
            print("write fail", symbol, type(exc).__name__, str(exc)[:80], flush=True)
        time.sleep(float(os.getenv("BP_XQ_DELAY", "0.4")))
    print("repair done:", repaired, "of", len(stale), flush=True)

    # 刷新极值表与基金规模表，保证 52 周位置/规模列用新数据
    with connect(app.db) as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "TRUNCATE bp_index_quote_extremes;"
                " INSERT INTO bp_index_quote_extremes (symbol, high_all, close_52w_ago, first_date, last_date)"
                " SELECT q.symbol, max(q.close),"
                "   (array_agg(q.close ORDER BY q.trade_date DESC))[251], min(q.trade_date), max(q.trade_date)"
                " FROM bp_index_quote_daily q WHERE q.adjust = 'bfq' GROUP BY q.symbol;"
            )
            conn.commit()
            print("extremes refreshed", flush=True)
        except Exception as exc:  # noqa: BLE001
            print("extremes refresh fail", type(exc).__name__, str(exc)[:100], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
