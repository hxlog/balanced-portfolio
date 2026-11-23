"""A 股 dataset runner：bfq=腾讯 qt 批量，hfq=腾讯 bfq × 新浪后复权因子。"""

from __future__ import annotations

from typing import Any, Sequence

from bp_etl import adapters
from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.registry import REGISTRY

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
        by_symbol = {bar.symbol: bar for bar in today_bfq}
        for code in codes:
            bar = by_symbol.get(code)
            if bar is None:
                continue
            sina_symbol, _ = adapters.tencent.split_market(code)
            try:
                factors = adapters.sina.fetch_hfq_factor(sina_channel, sina_symbol)
            except Exception:  # noqa: BLE001 - 因子单只失败下次波次再补
                continue
            out.extend(adapters.sina.build_hfq_from_bfq([bar], factors))
        return out
