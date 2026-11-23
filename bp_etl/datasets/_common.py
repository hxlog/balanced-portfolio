"""dataset runner 公共工具：线程池 + 共享限速通道 + 缺口回退。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Sequence

from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager

logger = logging.getLogger(__name__)


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
