"""港股 dataset runner：bfq=新浪日线，hfq=腾讯 hkfqkline（EM relay 兜底）。"""

from __future__ import annotations

import logging
import os
from typing import Any, Sequence

from bp_etl import adapters
from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.datasets._common import (
    existing_symbols,
    fetch_parallel,
    missing_symbols,
    reanchor_fallback_bars,
)
from bp_etl.registry import REGISTRY

logger = logging.getLogger(__name__)

UNIVERSE_SQL = (
    "SELECT stock_code FROM bp_stock_master"
    " WHERE market = 'HK' AND is_delisted = FALSE ORDER BY stock_code"
)


class HKStockRunner:
    spec = REGISTRY["hk_stock"]

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
        if adjust == "bfq":
            # 操作开关：BP_HK_BFQ_PRIMARY=sina|tencent（新浪 akshare 限流时用腾讯 fqkline，
            # 不复权原始价跨源一致；默认 sina 以保持历史锚一致）
            primary = (os.getenv("BP_HK_BFQ_PRIMARY") or "sina").strip().lower()
            done = existing_symbols(
                "bp_stock_quote_daily",
                "symbol",
                "tencent_hk_kline" if primary == "tencent" else "sina_hk_kline",
                "bfq",
                trade_date,
            )
            pending = [code for code in codes if code not in done]
            if primary == "tencent":
                return fetch_parallel(
                    pending, channels, "tencent_hk_kline",
                    lambda ch, code: adapters.tencent.fetch_kline(
                        ch, code, "bfq", trade_date, trade_date, market="HK", count=30,
                    ),
                )
            rows = fetch_parallel(
                pending, channels, "sina_hk_kline",
                lambda ch, code: adapters.sina.fetch_hk_bfq(ch, code, trade_date, trade_date),
            )
            missing = missing_symbols(pending, rows, trade_date)
            if missing:
                # 新浪 akshare 对部分港股代码限流/不可达：腾讯 fqkline bfq 兜底（原始价跨源一致）
                rows.extend(
                    fetch_parallel(
                        missing, channels, "tencent_hk_kline",
                        lambda ch, code: adapters.tencent.fetch_kline(
                            ch, code, "bfq", trade_date, trade_date, market="HK", count=30,
                        ),
                    )
                )
            return rows
        if adjust != "hfq":
            raise ValueError(f"不支持的 adjust: {adjust}")
        done = existing_symbols(
            "bp_stock_quote_daily", "symbol", "tencent_hk_kline", "hfq", trade_date
        )
        pending = [code for code in codes if code not in done]
        rows = fetch_parallel(
            pending, channels, "tencent_hk_kline",
            lambda ch, code: adapters.tencent.fetch_kline(
                ch, code, "hfq", trade_date, trade_date, market="HK", count=30,
            ),
        )
        missing = missing_symbols(codes, rows, trade_date)
        if missing:
            try:
                em_channel = channels.get("em_kline")
                if getattr(em_channel, "channel_kind", "direct") != "direct":
                    em_bars = fetch_parallel(
                        missing, channels, "em_kline",
                        lambda ch, code: adapters.eastmoney.fetch_kline(
                            ch, code, "hfq", trade_date, trade_date, market="HK",
                        ),
                        workers=3,
                    )
                    # EM 后复权基准与腾讯锚不同：必须重锚后再入库（否则同序列混基准）
                    rows.extend(
                        reanchor_fallback_bars(
                            em_bars,
                            table="bp_stock_quote_daily",
                            key_column="symbol",
                            anchor_source="tencent_hk_kline",
                            adjust="hfq",
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - EM 兜底失败靠下一波继续
                logger.warning("港股 hfq EM 兜底失败: %s", type(exc).__name__)
        return rows