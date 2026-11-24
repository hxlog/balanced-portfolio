"""dataset runner 公共工具：线程池 + 共享限速通道 + 缺口回退。"""

from __future__ import annotations

import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Sequence

from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager

logger = logging.getLogger(__name__)

# akshare 内部 requests 多数不传 timeout：设置全局 socket 默认超时，避免个别标的
# 被源限流后单次请求无限挂起（2026-11-23 生产 HK bfq 卡住的根因之一）。
socket.setdefaulttimeout(20)


def existing_symbols(
    table: str, key_column: str, source: str, adjust: str, trade_date: Any
) -> set[str]:
    """查询当日已落库的标的（用于重试/追赶时跳过已完成部分，显著降低重复请求）。"""
    try:
        from bp_ingest.config import load_config  # noqa: PLC0415
        from bp_ingest.db import connect  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return set()
    try:
        with connect(load_config().db) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT {key_column} FROM {table}"
                f" WHERE source=%s AND adjust=%s AND trade_date=%s",
                (source, adjust, trade_date),
            )
            return {row[0] for row in cur.fetchall()}
    except Exception:  # noqa: BLE001
        return set()


def fetch_parallel(
    codes: Sequence[str],
    channels: ChannelManager,
    source: str,
    fn: Callable[[Any, str], list[Bar]],
    *,
    workers: int = 4,
) -> list[Bar]:
    """多线程抓取；每个线程独立会话、共享同源全局限速桶（防限流）。"""
    out: list[Bar] = []

    def worker(code: str) -> list[Bar]:
        channel = channels.spawn(source)
        try:
            return fn(channel, code)
        except Exception as exc:  # noqa: BLE001 - 单标的失败不影响整体
            logger.debug("%s %s 失败: %s", source, code, type(exc).__name__)
            return []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rows in pool.map(worker, codes):
            out.extend(rows)
    return out


def missing_symbols(codes: Iterable[str], rows: Sequence[Any], trade_date: Any) -> list[str]:
    got = {row.symbol for row in rows if row.trade_date == trade_date}
    return [code for code in codes if code not in got]

def load_anchor_bars(
    table: str, key_column: str, symbol: str, source: str, adjust: str, *, days: int = 90
) -> list:
    """读取锚定源的近期历史（供回退源重锚使用）。"""
    from bp_etl.adapters.base import Bar
    from bp_ingest.config import load_config
    from bp_ingest.db import connect

    try:
        with connect(load_config().db) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT trade_date, open, high, low, close, volume, amount"
                f" FROM {table} WHERE {key_column}=%s AND source=%s AND adjust=%s"
                f" AND trade_date >= current_date - %s ORDER BY trade_date",
                (symbol, source, adjust, days),
            )
            rows = cur.fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [
        Bar(
            symbol=symbol, trade_date=row[0],
            open=float(row[1]) if row[1] is not None else None,
            high=float(row[2]) if row[2] is not None else None,
            low=float(row[3]) if row[3] is not None else None,
            close=float(row[4]), volume=int(row[5]) if row[5] is not None else None,
            amount=float(row[6]) if row[6] is not None else None,
            source=source, adjust=adjust,
        )
        for row in rows
        if row[4] is not None
    ]


def reanchor_fallback_bars(
    bars: list,
    *,
    table: str,
    key_column: str,
    anchor_source: str,
    adjust: str,
    trade_date=None,
) -> list:
    """把回退源 bars 重锚到锚定源基准（无重叠日的标的丢弃，绝不混入不同基准）。"""
    from bp_etl.anchors import NoOverlapError, reanchor

    grouped: dict[str, list] = {}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    out: list = []
    for symbol, symbol_bars in grouped.items():
        anchor_bars = load_anchor_bars(table, key_column, symbol, anchor_source, adjust)
        if not anchor_bars:
            logger.warning("回退源重锚跳过 %s：无锚定源历史", symbol)
            continue
        try:
            out.extend(reanchor(anchor_bars, symbol_bars))
        except NoOverlapError:
            logger.warning("回退源重锚跳过 %s：无重叠交易日", symbol)
    if trade_date is not None:
        out = [bar for bar in out if bar.trade_date == trade_date]
    return out
