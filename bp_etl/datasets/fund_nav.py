"""场外基金净值 runner：rankhandler 批量榜 + lsjz 逐只补缺。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Sequence

from bp_etl import adapters
from bp_etl.adapters.base import NavRow
from bp_etl.channels import ChannelManager
from bp_etl.registry import REGISTRY

logger = logging.getLogger(__name__)

UNIVERSE_SQL = "SELECT fund_code FROM bp_fund_master ORDER BY fund_code"


class FundNavRunner:
    spec = REGISTRY["fund_nav"]

    def universe(self, conn: Any) -> list[str]:
        with conn.cursor() as cur:
            cur.execute(UNIVERSE_SQL)
            return [row[0] for row in cur.fetchall()]

    def expected_count(self, conn: Any, trade_date: Any) -> int:
        """可发布子集：上一交易日已发布净值的基金数（货币/QDII 等晚发布不计入分母）。"""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM bp_fund_nav_daily WHERE trade_date = ("
                " SELECT max(trade_date) FROM bp_fund_nav_daily WHERE trade_date < %s)",
                (trade_date,),
            )
            row = cur.fetchone()
        return int(row[0]) if row and row[0] else 0

    def fetch(
        self,
        adjust: str,
        codes: Sequence[str],
        trade_date: Any,
        channels: ChannelManager,
    ) -> list[NavRow]:
        rank_channel = channels.get("em_rankhandler")
        rows, pages = adapters.eastmoney.fetch_rankhandler(rank_channel, page=1)
        for page in range(2, max(pages, 1) + 1):
            page_rows, _ = adapters.eastmoney.fetch_rankhandler(rank_channel, page=page)
            if not page_rows:
                break
            rows.extend(page_rows)
        got = {row.fund_code for row in rows if row.trade_date == trade_date}
        missing = [code for code in codes if code not in got]
        if not missing:
            return rows

        def worker(code: str) -> list[NavRow]:
            channel = channels.spawn("em_lsjz")
            try:
                return [
                    row for row in adapters.eastmoney.fetch_lsjz(channel, code, page_size=10)
                    if row.trade_date <= trade_date
                ]
            except Exception:  # noqa: BLE001 - 单只失败下一波重试
                return []

        extra: list[NavRow] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for fund_rows in pool.map(worker, missing):
                extra.extend(fund_rows)
        return rows + extra
