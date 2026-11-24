"""ETF/LOF dataset runner：bfq=腾讯 qt 批量，hfq=腾讯 kline（EM relay 兜底）。"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
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

UNIVERSE_SQL = "SELECT etf_code FROM bp_etf_master ORDER BY etf_code"


class ETFRunner:
    spec = REGISTRY["etf"]

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
            done = existing_symbols(
                "bp_etf_quote_daily", "etf_code", "tencent_qt", "bfq", trade_date
            )
            pending = [code for code in codes if code not in done]
            rows = adapters.tencent.fetch_qt_batch(channels.get("tencent_qt"), pending)
            missing = missing_symbols(pending, rows, trade_date)
            if missing:
                # 腾讯 qt 缺报价（停牌/代码缺失）：EM 不复权原始价兜底（跨源一致）
                try:
                    rows.extend(
                        fetch_parallel(
                            missing, channels, "em_kline",
                            lambda ch, code: adapters.eastmoney.fetch_kline(
                                ch, code, "bfq", trade_date, trade_date,
                            ),
                            workers=3,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ETF bfq EM 兜底失败: %s", type(exc).__name__)
            return rows
        if adjust != "hfq":
            raise ValueError(f"不支持的 adjust: {adjust}")
        done = existing_symbols(
            "bp_etf_quote_daily", "etf_code", "tencent_kline", "hfq", trade_date
        )
        pending = [code for code in codes if code not in done]
        primary = (os.getenv("BP_ETF_HFQ_PRIMARY") or "tencent").strip().lower()
        window_start = trade_date - timedelta(days=90)
        rows: list[Bar] = []

        def _merge(window_bars: list) -> list[str]:
            if not window_bars:
                return missing_symbols(codes, rows, trade_date)
            reanchored = reanchor_fallback_bars(
                window_bars,
                table="bp_etf_quote_daily",
                key_column="etf_code",
                anchor_source="tencent_etf_kline",
                adjust="hfq",
                trade_date=trade_date,
            )
            rows.extend(reanchored)
            return missing_symbols(codes, rows, trade_date)

        if primary == "tencent":
            rows = fetch_parallel(
                pending, channels, "tencent_kline",
                lambda ch, code: adapters.tencent.fetch_kline(
                    ch, code, "hfq", trade_date, trade_date, market="A", count=30,
                ),
            )
        if primary in ("tencent", "sina"):
            missing = missing_symbols(codes, rows, trade_date)
            if missing:
                sina_bars = fetch_parallel(
                    missing, channels, "sina_kline",
                    lambda ch, code: adapters.sina.fetch_etf_hfq(
                        ch, code, window_start, trade_date
                    ),
                )
                missing = _merge(sina_bars)
        missing = missing_symbols(codes, rows, trade_date)
        if missing:
            try:
                em_channel = channels.get("em_kline")
                if getattr(em_channel, "channel_kind", "direct") != "direct":
                    em_bars = fetch_parallel(
                        missing, channels, "em_kline",
                        lambda ch, code: adapters.eastmoney.fetch_kline(
                            ch, code, "hfq", window_start, trade_date,
                        ),
                        workers=3,
                    )
                    _merge(em_bars)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ETF hfq EM 兜底失败: %s", type(exc).__name__)
        return rows