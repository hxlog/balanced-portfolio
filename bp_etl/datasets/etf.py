"""ETF/LOF dataset runner：bfq=腾讯 qt 批量，hfq=腾讯 kline（EM relay 兜底）。"""

from __future__ import annotations

import logging
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
            return adapters.tencent.fetch_qt_batch(channels.get("tencent_qt"), pending)
        if adjust != "hfq":
            raise ValueError(f"不支持的 adjust: {adjust}")
        done = existing_symbols(
            "bp_etf_quote_daily", "etf_code", "tencent_kline", "hfq", trade_date
        )
        pending = [code for code in codes if code not in done]
        rows = fetch_parallel(
            pending, channels, "tencent_kline",
            lambda ch, code: adapters.tencent.fetch_kline(
                ch, code, "hfq", trade_date, trade_date, market="A", count=30,
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
                            ch, code, "hfq", trade_date, trade_date,
                        ),
                        workers=3,
                    )
                    rows.extend(
                        reanchor_fallback_bars(
                            em_bars,
                            table="bp_etf_quote_daily",
                            key_column="etf_code",
                            anchor_source="tencent_etf_kline",
                            adjust="hfq",
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ETF hfq EM 兜底失败: %s", type(exc).__name__)
        return rows