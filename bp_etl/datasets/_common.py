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