"""ETF/LOF dataset runner：bfq=腾讯 qt 批量，hfq=腾讯 kline（EM relay 兜底）。"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Sequence

from bp_etl import adapters
from bp_etl.adapters.base import Bar
from bp_etl.adapters.sina import A_HFQ_FACTOR_URL, parse_hfq_factor
from bp_etl.channels import ChannelManager
from bp_etl.adapters.tencent import split_market
from bp_etl.datasets._common import (
    existing_symbols,
    fetch_parallel,
    missing_symbols,
    reanchor_fallback_bars,
)
from bp_etl.registry import REGISTRY

logger = logging.getLogger(__name__)

UNIVERSE_SQL = "SELECT etf_code FROM bp_etf_master ORDER BY etf_code"


def _factor_on(factors: list, day: Any) -> float:
    current = None
    for point_day, value in factors:
        if point_day <= day:
            current = value
        else:
            break
    return current or 0.0


def _scale(value: Any, scale: float) -> float | None:
    return None if value is None else float(value) * scale


class ETFRunner:
    spec = REGISTRY["etf"]

    def universe(self, conn: Any) -> list[str]:
        with conn.cursor() as cur:
            cur.execute(UNIVERSE_SQL)
            return [row[0] for row in cur.fetchall()]

    def _factor_derive(
        self, codes: Sequence[str], trade_date: Any, channels: ChannelManager
    ) -> list[Bar]:
        """ETF hfq 因子快速补齐：hfq = bfq × 新浪因子 × 基准比（R）。

        R = 腾讯锚 hfq / (bfq × 当日新浪因子)，取最近重叠交易日，常数（除权日出因子自动跟进）。
        只对当日 bfq 已存在且锚定源有历史的标的生效；数据量小、无 V8 解码，比 akshare 快一个量级。
        """
        from datetime import date as _date, timedelta

        from bp_ingest.config import load_config
        from bp_ingest.db import connect

        today = _date.fromisoformat(str(trade_date)[:10]) if not isinstance(trade_date, _date) else trade_date
        start = today - timedelta(days=120)
        wanted = set(codes)
        out: list[Bar] = []
        with connect(load_config().db) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT etf_code, trade_date, open, high, low, close, volume, amount"
                " FROM bp_etf_quote_daily WHERE adjust='bfq' AND source='tencent_qt'"
                " AND trade_date=%s AND etf_code = ANY(%s)",
                (today, list(wanted)),
            )
            bfq_today = {row[0]: row for row in cur.fetchall()}
            if not bfq_today:
                return []
            cur.execute(
                "SELECT etf_code, trade_date, close FROM bp_etf_quote_daily"
                " WHERE adjust='hfq' AND source='tencent_etf_kline' AND trade_date >= %s"
                " AND etf_code = ANY(%s) ORDER BY trade_date",
                (start, list(bfq_today)),
            )
            anchor: dict[str, list] = {}
            for code, d, close in cur.fetchall():
                anchor.setdefault(code, []).append((d, float(close)))
            cur.execute(
                "SELECT etf_code, trade_date, close FROM bp_etf_quote_daily"
                " WHERE adjust='bfq' AND trade_date >= %s AND etf_code = ANY(%s)"
                " ORDER BY trade_date",
                (start, list(bfq_today)),
            )
            bfq_hist: dict[str, dict] = {}
            for code, d, close in cur.fetchall():
                bfq_hist.setdefault(code, {})[d] = float(close)
        channel = channels.get("sina_kline")
        for code, row in bfq_today.items():
            sym, _m = split_market(code)
            try:
                channel.throttle()
                response = channel.get(A_HFQ_FACTOR_URL.format(sym), timeout=20)
                factors = parse_hfq_factor(response.text, source="sina_etf_kline")
            except Exception:  # noqa: BLE001 - 单只失败靠下一波
                continue
            points = [p for p in factors if p[0] <= today]
            if not points:
                continue
            factor_today = points[-1][1]
            anchor_rows = anchor.get(code) or []
            ratios = [
                a_close / (bfq_hist.get(code, {}).get(d) * _factor_on(factors, d))
                for d, a_close in anchor_rows
                if bfq_hist.get(code, {}).get(d) and _factor_on(factors, d)
            ]
            if not ratios:
                continue
            ratio = sorted(ratios)[len(ratios) // 2]  # 中位数抗单日异常
            if abs(ratio - 1.0) > 1e6 or ratio <= 0:
                continue
            scale = factor_today * ratio
            out.append(
                Bar(
                    symbol=code, trade_date=today,
                    open=_scale(row[2], scale), high=_scale(row[3], scale),
                    low=_scale(row[4], scale), close=_scale(row[5], scale),
                    volume=int(row[6]) if row[6] is not None else None,
                    amount=float(row[7]) if row[7] is not None else None,
                    source="sina_etf_kline:factor", adjust="hfq",
                )
            )
        return out

    def expected_count(self, conn: Any, trade_date: Any, adjust: str = "bfq") -> int:
        """当日可交易子集 = 上一交易日**同口径**实际有行情的 ETF 数。"""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(DISTINCT etf_code) FROM bp_etf_quote_daily"
                " WHERE adjust=%s AND trade_date ="
                " (SELECT max(trade_date) FROM bp_etf_quote_daily"
                "  WHERE adjust=%s AND trade_date < %s)",
                (adjust, adjust, trade_date),
            )
            row = cur.fetchone()
        return int(row[0]) if row and row[0] else 0

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
                return missing_symbols(pending, rows, trade_date)
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
        if (os.getenv("BP_ETF_HFQ_PRIMARY") or "").strip().lower() == "factor":
            done = existing_symbols(
                "bp_etf_quote_daily", "etf_code", "tencent_etf_kline", "hfq", trade_date
            )
            pending = [code for code in codes if code not in done]
            return self._factor_derive(pending, trade_date, channels)
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