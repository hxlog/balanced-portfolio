"""雪球指数行情回填：补齐东财/中证官网被限流期间的指数日线。

雪球 v5 K 线接口境内直连可用（需先访问首页拿 cookie），且覆盖中证系 930xxx/H3xxxx：
    CSI930641 / CSIH30007 / SH000300 / SZ399006
返回完整 OHLCV 历史（count=-2000 约 8 年），可直接补齐 52 周高低所需样本。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, "/opt/balanced-portfolio")

import requests

from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import QuoteRow, connect, upsert_quotes
from bp_ingest.http_session import install_hardened_session

SOURCE = "cn_index_xueqiu"
HOME = "https://xueqiu.com/about"
KLINE = "https://stock.xueqiu.com/v5/stock/chart/kline.json"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
COUNT = int(os.getenv("BP_XQ_COUNT", "-2000"))
BUDGET_SECONDS = int(os.getenv("BP_XQ_BUDGET", "2400"))
ALL_SYMBOLS = os.getenv("BP_XQ_ALL", "").strip() in ("1", "true", "yes")
DELAY = float(os.getenv("BP_XQ_DELAY", "0.9"))


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://xueqiu.com/"})
    session.get(HOME, timeout=20)
    return session


def candidate_symbols(symbol: str) -> list[str]:
    if symbol.startswith("H") and symbol[1:2].isdigit():
        return [f"CSI{symbol}", symbol]
    if symbol[:1] in ("0", "3") and symbol[:2] not in ("93", "95", "97", "98"):
        return [f"SH{symbol}", symbol]
    return [f"CSI{symbol}", f"SH{symbol}", f"SZ{symbol}", symbol]


def fetch_kline(session: requests.Session, xq_symbol: str) -> list[dict]:
    end_ms = int(time.time() * 1000)
    params = {
        "symbol": xq_symbol,
        "begin": str(end_ms),
        "period": "day",
        "type": "before",
        "count": str(COUNT),
        "indicator": "kline",
    }
    response = session.get(KLINE, params=params, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"http {response.status_code}")
    payload = response.json()
    data = payload.get("data") or {}
    columns = data.get("column") or []
    items = data.get("item") or []
    return [dict(zip(columns, item)) for item in items]


def to_rows(symbol: str, items: list[dict]) -> list[QuoteRow]:
    rows: list[QuoteRow] = []
    for item in items:
        ts = item.get("timestamp")
        close = item.get("close")
        if ts is None or close is None:
            continue
        try:
            trade_date = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).date()
        except Exception:  # noqa: BLE001
            continue
        rows.append(
            QuoteRow(
                trade_date=trade_date,
                symbol=symbol,
                source=SOURCE,
                category="index",
                name=symbol,
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=close,
                volume=int(item["volume"]) if item.get("volume") else None,
                amount=item.get("amount"),
                turnover_rate=item.get("turnoverrate"),
                pct_change=item.get("percent"),
                adjust="bfq",
            ),
        )
    rows.sort(key=lambda row: row.trade_date)
    return rows


def main() -> int:
    setup_logging()
    install_hardened_session()
    app = load_config()
    session = make_session()
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
    missing = symbols if ALL_SYMBOLS else [symbol for symbol in symbols if symbol not in have]
    print("index symbols:", len(symbols), "targets:", len(missing), "mode:", "all" if ALL_SYMBOLS else "missing", flush=True)

    started = time.time()
    ok = 0
    skipped = 0
    for symbol in missing:
        if time.time() - started > BUDGET_SECONDS:
            print("budget exhausted", flush=True)
            break
        rows: list[QuoteRow] = []
        for xq_symbol in candidate_symbols(symbol):
            try:
                items = fetch_kline(session, xq_symbol)
            except Exception as exc:  # noqa: BLE001
                print("fetch fail", symbol, xq_symbol, type(exc).__name__, flush=True)
                time.sleep(2)
                continue
            if items:
                rows = to_rows(symbol, items)
                if rows:
                    break
            time.sleep(0.3)
        if not rows:
            skipped += 1
            print("skip", symbol, flush=True)
            time.sleep(DELAY)
            continue
        with connect(app.db) as conn:
            conn.autocommit = False
            for start in range(0, len(rows), 500):
                upsert_quotes(conn, rows[start : start + 500])
            conn.commit()
        ok += 1
        print("ok %s rows=%d ok_total=%d skip=%d elapsed=%.0fs" % (
            symbol, len(rows), ok, skipped, time.time() - started), flush=True)
        time.sleep(DELAY)
    print("done ok=%d skipped=%d elapsed=%.0fs" % (ok, skipped, time.time() - started), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
