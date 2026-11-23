"""幂等写入 + pct 补全 + 增量覆盖快照。

设计 §5/§8：
- 原始行情表保留 source 维度（审计 + 多源聚合）；写入按主键 UPSERT；
- 源未提供 pct_change 时按库内 prev_close 本地计算（与既有 ingest 规则一致）；
- bp_asset_coverage 改为增量 UPSERT（不再 TRUNCATE 全量重建）。
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Sequence

from bp_etl.adapters.base import Bar, NavRow
from bp_etl.adapters.base import AdapterError
from bp_etl.registry import DatasetSpec

_BAR_UPSERT: dict[str, str] = {
    "bp_stock_quote_daily": (
        "INSERT INTO bp_stock_quote_daily"
        " (symbol, trade_date, source, adjust, open, high, low, close, volume, amount, pct_change)"
        " VALUES (%(key)s, %(trade_date)s, %(source)s, %(adjust)s, %(open)s, %(high)s,"
        " %(low)s, %(close)s, %(volume)s, %(amount)s, %(pct_change)s)"
        " ON CONFLICT (symbol, trade_date, source, adjust) DO UPDATE SET"
        " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,"
        " volume=EXCLUDED.volume, amount=EXCLUDED.amount, pct_change=EXCLUDED.pct_change"
    ),
    "bp_index_quote_daily": (
        "INSERT INTO bp_index_quote_daily"
        " (symbol, trade_date, source, adjust, open, high, low, close, volume, amount, pct_change)"
        " VALUES (%(key)s, %(trade_date)s, %(source)s, %(adjust)s, %(open)s, %(high)s,"
        " %(low)s, %(close)s, %(volume)s, %(amount)s, %(pct_change)s)"
        " ON CONFLICT (symbol, source, adjust, trade_date) DO UPDATE SET"
        " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,"
        " volume=EXCLUDED.volume, amount=EXCLUDED.amount, pct_change=EXCLUDED.pct_change"
    ),
    "bp_etf_quote_daily": (
        "INSERT INTO bp_etf_quote_daily"
        " (etf_code, trade_date, source, adjust, open, high, low, close, volume, amount, pct_change)"
        " VALUES (%(key)s, %(trade_date)s, %(source)s, %(adjust)s, %(open)s, %(high)s,"
        " %(low)s, %(close)s, %(volume)s, %(amount)s, %(pct_change)s)"
        " ON CONFLICT (etf_code, trade_date, source, adjust) DO UPDATE SET"
        " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,"
        " volume=EXCLUDED.volume, amount=EXCLUDED.amount, pct_change=EXCLUDED.pct_change"
    ),
}

_NAV_UPSERT = (
    "INSERT INTO bp_fund_nav_daily (fund_code, trade_date, nav, acc_nav, source)"
    " VALUES (%s, %s, %s, %s, %s)"
    " ON CONFLICT (fund_code, trade_date) DO UPDATE SET"
    " nav=EXCLUDED.nav, acc_nav=COALESCE(EXCLUDED.acc_nav, bp_fund_nav_daily.acc_nav),"
    " source=EXCLUDED.source"
)

_COVERAGE_UPSERT = (
    "INSERT INTO bp_asset_coverage (kind, code, adjust, last_date, updated_at)"
    " VALUES (%s, %s, %s, %s, now())"
    " ON CONFLICT (kind, code, adjust) DO UPDATE SET"
    " last_date=GREATEST(bp_asset_coverage.last_date, EXCLUDED.last_date),"
    " updated_at=now()"
)


class WriterError(AdapterError):
    """写入/覆盖刷新失败。"""


def _prev_close(conn, dataset: DatasetSpec, key: str, before: date) -> float | None:
    sql = (
        f"SELECT close FROM {dataset.table}"
        f" WHERE {dataset.key_column} = %s AND trade_date < %s"
        " ORDER BY trade_date DESC LIMIT 1"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (key, before))
        row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def fill_pct_change(conn, dataset: DatasetSpec, bars: Sequence[Bar]) -> list[Bar]:
    """补全 pct_change（源缺失时按库内前收 + 本批前一行计算）。"""
    if not bars:
        return []
    grouped: dict[str, list[Bar]] = {}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    filled: list[Bar] = []
    for symbol, group in grouped.items():
        ordered = sorted(group, key=lambda item: item.trade_date)
        if any(bar.pct_change is not None for bar in ordered):
            filled.extend(ordered)
            continue
        base = _prev_close(conn, dataset, symbol, ordered[0].trade_date)
        previous: float | None = base
        for bar in ordered:
            pct: float | None = None
            if previous is not None and previous > 0:
                pct = (bar.close / previous - 1.0) * 100.0
            filled.append(
                Bar(
                    symbol=bar.symbol, trade_date=bar.trade_date, open=bar.open,
                    high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
                    amount=bar.amount, pct_change=pct, source=bar.source, adjust=bar.adjust,
                )
            )
            previous = bar.close
    return filled


def write_bars(conn, dataset: DatasetSpec, bars: Sequence[Bar]) -> int:
    """写 bar 数据集（幂等）；返回处理行数。"""
    if dataset.value_kind != "bar":
        raise WriterError(f"{dataset.name}: 非 bar 数据集")
    sql = _BAR_UPSERT.get(dataset.table)
    if sql is None:
        raise WriterError(f"{dataset.name}: 未知表 {dataset.table}")
    rows = fill_pct_change(conn, dataset, bars)
    if not rows:
        return 0
    payload = [
        {
            "key": bar.symbol,
            "trade_date": bar.trade_date,
            "source": bar.source,
            "adjust": bar.adjust,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "amount": bar.amount,
            "pct_change": bar.pct_change,
        }
        for bar in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, payload)
    return len(payload)


def write_navs(conn, rows: Iterable[NavRow]) -> int:
    payload = [(row.fund_code, row.trade_date, row.nav, row.acc_nav, row.source) for row in rows]
    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_NAV_UPSERT, payload)
    return len(payload)


def refresh_coverage(conn, dataset: DatasetSpec, codes: Sequence[str]) -> int:
    """按受影响标的增量刷新 bp_asset_coverage（不删除其它 kind 行）。"""
    if not codes:
        return 0
    if dataset.value_kind == "nav":
        sql = (
            "SELECT fund_code, '' AS adjust, max(trade_date) FROM bp_fund_nav_daily"
            " WHERE fund_code = ANY(%s) GROUP BY fund_code"
        )
        with conn.cursor() as cur:
            cur.execute(sql, (list(codes),))
            rows = cur.fetchall()
        payload = [(dataset.coverage_kind, code, "", last) for code, _, last in rows]
    else:
        sql = (
            f"SELECT {dataset.key_column}, adjust, max(trade_date) FROM {dataset.table}"
            f" WHERE {dataset.key_column} = ANY(%s) GROUP BY 1, 2"
        )
        with conn.cursor() as cur:
            cur.execute(sql, (list(codes),))
            rows = cur.fetchall()
        payload = [(dataset.coverage_kind, code, adjust, last) for code, adjust, last in rows]
    payload = [row for row in payload if row[3] is not None]
    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_COVERAGE_UPSERT, payload)
    return len(payload)