"""行情清洗: 按 A股交易日历对齐 + 线性插值, 构建物化表 bp_quote_clean。

规则:
  1. 以 A股交易日历为基准, 把每个 (symbol, source) 的原始序列 reindex 到
     其[首个真实值, 最后真实值]区间内的 A股交易日 → 剔除所有 A股非交易日的行。
  2. 内部缺口(两侧均有真实值)用线性插值填充, fill_flag=interp。
  3. 前导/尾部不外推(区间端点本身即真实值, 故区间内不会出现无锚点缺口)。
     "某资产相对其他资产停更" 的尾部缺口在回测构面板时检测并报错(见 backtest)。
  4. 基于清洗后 close 重算日简单收益 ret。

提供 rebuild_clean() 供 bp_ingest 增量刷新或独立全量构建调用。
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import psycopg

from bp_ingest.calendar import TradingCalendar

logger = logging.getLogger(__name__)


_UPSERT_SQL = """
INSERT INTO bp_quote_clean
    (trade_date, symbol, source, close, open, high, low, volume, ret, fill_flag)
VALUES
    (%(trade_date)s, %(symbol)s, %(source)s, %(close)s, %(open)s, %(high)s,
     %(low)s, %(volume)s, %(ret)s, %(fill_flag)s)
ON CONFLICT (symbol, source, trade_date) DO UPDATE SET
    close     = EXCLUDED.close,
    open      = EXCLUDED.open,
    high      = EXCLUDED.high,
    low       = EXCLUDED.low,
    volume    = EXCLUDED.volume,
    ret       = EXCLUDED.ret,
    fill_flag = EXCLUDED.fill_flag,
    updated_at = now()
"""


def _load_raw(conn: psycopg.Connection, symbol: str, source: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trade_date, open, high, low, close, volume
            FROM bp_index_quote_daily
            WHERE symbol = %s AND source = %s
            ORDER BY trade_date
            """,
            (symbol, source),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        rows, columns=["trade_date", "open", "high", "low", "close", "volume"]
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df.set_index("trade_date").sort_index()


def _list_targets(
    conn: psycopg.Connection, symbols: Optional[list[str]]
) -> list[tuple[str, str]]:
    sql = "SELECT DISTINCT symbol, source FROM bp_index_quote_daily"
    params: list = []
    if symbols:
        sql += " WHERE symbol = ANY(%s)"
        params.append(symbols)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [(r[0], r[1]) for r in cur.fetchall()]


def clean_one(
    conn: psycopg.Connection, symbol: str, source: str, cal: TradingCalendar
) -> int:
    """清洗单个 (symbol, source) 并写入 bp_quote_clean。返回写入行数。"""
    raw = _load_raw(conn, symbol, source)
    if raw.empty:
        return 0

    first, last = raw.index.min(), raw.index.max()
    a_days = cal.trading_days_between(first, last)
    if not a_days:
        return 0

    idx = pd.Index(a_days, name="trade_date")
    panel = raw.reindex(idx)

    real_mask = panel["close"].notna()
    # 线性插值: 仅内部缺口(limit_area="inside" 不外推; 端点为真实值故区间内必有锚点)
    close = panel["close"].interpolate(method="linear", limit_area="inside")
    open_ = panel["open"].interpolate(method="linear", limit_area="inside")
    high = panel["high"].interpolate(method="linear", limit_area="inside")
    low = panel["low"].interpolate(method="linear", limit_area="inside")
    volume = panel["volume"]  # 插值日成交量留空(NaN)

    ret = close.pct_change()

    payload = []
    for d in idx:
        c = close.loc[d]
        if pd.isna(c):
            continue
        v = volume.loc[d]
        r = ret.loc[d]
        payload.append(
            {
                "trade_date": d,
                "symbol": symbol,
                "source": source,
                "close": float(c),
                "open": None if pd.isna(open_.loc[d]) else float(open_.loc[d]),
                "high": None if pd.isna(high.loc[d]) else float(high.loc[d]),
                "low": None if pd.isna(low.loc[d]) else float(low.loc[d]),
                "volume": None if pd.isna(v) else int(v),
                "ret": None if pd.isna(r) else float(r),
                "fill_flag": "real" if bool(real_mask.loc[d]) else "interp",
            }
        )

    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, payload)

    interp_n = sum(1 for p in payload if p["fill_flag"] == "interp")
    if interp_n:
        logger.info("清洗 %s@%s: %d 行(插值 %d)", symbol, source, len(payload), interp_n)
    return len(payload)


def rebuild_clean(
    conn: psycopg.Connection,
    symbols: Optional[list[str]] = None,
    cal: Optional[TradingCalendar] = None,
) -> int:
    """重建 bp_quote_clean。symbols 为空则处理全部标的。返回总写入行数。"""
    if cal is None:
        cal = TradingCalendar()
        cal.load()
    targets = _list_targets(conn, symbols)
    total = 0
    for symbol, source in targets:
        try:
            total += clean_one(conn, symbol, source, cal)
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            logger.error("清洗失败 %s@%s: %s", symbol, source, exc)
    logger.info("清洗完成: 标的=%d 写入行=%d", len(targets), total)
    return total
