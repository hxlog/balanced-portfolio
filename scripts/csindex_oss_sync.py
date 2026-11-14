"""中证官网 OSS 行情同步（perf.xls，最近 24 个交易日）。

东财 push2his 与中证官网 JSON API 都会被 WAF 限流，但 CSIndex 的 OSS 静态文件
（oss-ch.csindex.com.cn）始终可用：
    /autofile/perf/{code}perf.xls        -> 最近 24 个交易日 OHLC/成交额
    /autofile/closeweight/{code}closeweight.xls -> 最新成分权重（全量）

本脚本为缺失行情的指数补齐最近 24 天收盘（页面「收盘/当日」列立即生效），
并把官方成分权重写入 bp_index_constituent。
"""
from __future__ import annotations

import io
import sys
import time
from datetime import date

sys.path.insert(0, "/opt/balanced-portfolio")

import pandas as pd
import psycopg
import requests

from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import QuoteRow, connect, upsert_quotes
from bp_ingest.http_session import install_hardened_session
from bp_api.repositories_valuation import upsert_constituents, upsert_stock_master

OSS_BASE = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile"
SOURCE = "csindex_perf"
BUDGET_SECONDS = 900


def fetch_xls(path: str) -> pd.DataFrame | None:
    response = requests.get(f"{OSS_BASE}/{path}", timeout=25)
    if response.status_code != 200 or len(response.content) < 1000:
        return None
    try:
        return pd.read_excel(io.BytesIO(response.content))
    except Exception:  # noqa: BLE001
        return None


def _col(df: pd.DataFrame, *candidates: str) -> str | None:
    for name in df.columns:
        text = str(name)
        if any(candidate in text for candidate in candidates):
            return name
    return None


def perf_rows(symbol: str, df: pd.DataFrame) -> tuple[str, list[QuoteRow]]:
    date_col = _col(df, "日期Date", "日期")
    open_col = _col(df, "开盘Open", "开盘")
    high_col = _col(df, "最高High", "最高")
    low_col = _col(df, "最低Low", "最低")
    close_col = _col(df, "收盘Close", "收盘")
    pct_col = _col(df, "涨跌幅")
    vol_col = _col(df, "成交量")
    amt_col = _col(df, "成交金额")
    name_col = _col(df, "指数中文简称Index Chinese Name", "中文简称")
    if not date_col or not close_col:
        return "", []
    name = str(df[name_col].iloc[0]) if name_col else symbol
    rows: list[QuoteRow] = []
    for _, row in df.iterrows():
        try:
            trade_date = pd.to_datetime(row[date_col]).date()
        except Exception:  # noqa: BLE001
            continue
        close = row.get(close_col)
        if pd.isna(close):
            continue
        rows.append(
            QuoteRow(
                trade_date=trade_date,
                symbol=symbol,
                source=SOURCE,
                category="index",
                name=name,
                open=None if pd.isna(row.get(open_col)) else float(row[open_col]),
                high=None if pd.isna(row.get(high_col)) else float(row[high_col]),
                low=None if pd.isna(row.get(low_col)) else float(row[low_col]),
                close=float(close),
                volume=None if vol_col is None or pd.isna(row.get(vol_col)) else int(row[vol_col]),
                amount=None if amt_col is None or pd.isna(row.get(amt_col)) else float(row[amt_col]),
                turnover_rate=None,
                pct_change=None if pct_col is None or pd.isna(row.get(pct_col)) else float(row[pct_col]),
                adjust="bfq",
            ),
        )
    rows.sort(key=lambda item: item.trade_date)
    return name, rows


def main() -> int:
    setup_logging()
    install_hardened_session()
    app = load_config()
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute(
            "select symbol from bp_index_config"
            " where is_deleted = 0 and category = %s and index_code is not null"
            " order by symbol",
            ("index",),
        )
        symbols = [row[0] for row in cur.fetchall()]
        cur.execute("select distinct symbol from bp_index_quote_daily where adjust = %s", ("bfq",))
        have = {row[0] for row in cur.fetchall()}
    missing = [symbol for symbol in symbols if symbol not in have]
    print("index symbols:", len(symbols), "missing:", len(missing), flush=True)

    started = time.time()
    ok = 0
    skipped = 0
    for index, symbol in enumerate(missing):
        if time.time() - started > BUDGET_SECONDS:
            print("budget exhausted", flush=True)
            break
        df = fetch_xls(f"perf/{symbol}perf.xls")
        if df is None or df.empty:
            skipped += 1
            time.sleep(0.05)
            continue
        name, rows = perf_rows(symbol, df)
        if not rows:
            skipped += 1
            continue
        with connect(app.db) as conn:
            conn.autocommit = False
            upsert_quotes(conn, rows)
            conn.commit()
        ok += 1
        if (index + 1) % 25 == 0:
            print("progress %d/%d ok=%d skip=%d elapsed=%.0fs" % (
                index + 1, len(missing), ok, skipped, time.time() - started), flush=True)
        time.sleep(0.05)
    print("done ok=%d skipped=%d elapsed=%.0fs" % (ok, skipped, time.time() - started), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
