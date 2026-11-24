"""A 股 dataset runner：bfq=腾讯 qt 批量，hfq=腾讯 bfq × 新浪后复权因子。"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Sequence

from bp_etl import adapters
from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.datasets._common import existing_symbols
from bp_etl.registry import REGISTRY

logger = logging.getLogger(__name__)

UNIVERSE_SQL = (
    "SELECT stock_code FROM bp_stock_master"
    " WHERE market IN ('SH','SZ','BJ') AND is_delisted = FALSE"
    " ORDER BY stock_code"
)


class AStockRunner:
    spec = REGISTRY["a_stock"]

    def universe(self, conn: Any) -> list[str]:
        with conn.cursor() as cur:
            cur.execute(UNIVERSE_SQL)
            return [row[0] for row in cur.fetchall()]

    def fetch(
        self,
        adjust: str,
        codes: Sequence[str],
        trade_date: Any,
        channels: ChannelManager,
    ) -> list[Bar]:
        qt_channel = channels.get("tencent_qt")
        bfq_rows = adapters.tencent.fetch_qt_batch(qt_channel, codes)
        if adjust == "bfq":
            return bfq_rows
        if adjust != "hfq":
            raise ValueError(f"不支持的 adjust: {adjust}")
        today_bfq = [bar for bar in bfq_rows if bar.trade_date == trade_date]
        if not today_bfq:
            return []
        sina_channel = channels.get("sina_kline")
        out: list[Bar] = []
        done = existing_symbols(
            "bp_stock_quote_daily", "symbol", "sina_kline", "hfq", trade_date
        )
        by_symbol = {bar.symbol: bar for bar in today_bfq}
        pending = [code for code in codes if code not in done and code in by_symbol]

        def _one(code: str) -> list[Bar]:
            sina_symbol, _ = adapters.tencent.split_market(code)
            try:
                factors = adapters.sina.fetch_hfq_factor(sina_channel, sina_symbol)
                if not factors:
                    return []
                return adapters.sina.build_hfq_from_bfq([by_symbol[code]], factors)
            except Exception as exc:  # noqa: BLE001 - 单只失败/空因子不影响整波
                logger.warning("A股 hfq 因子失败 %s: %s", code, type(exc).__name__)
                return []

        # 因子请求是延迟瓶颈：并发 6 路（共享 TokenBucket 限速仍在 4/s），
        # 日更从 ~1 只/秒提升到接近限速上限。
        workers = int(os.getenv("BP_A_HFQ_WORKERS", "6") or "6")
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
            for bars in pool.map(_one, pending):
                out.extend(bars)
        return out