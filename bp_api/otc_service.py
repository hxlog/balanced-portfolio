"""场外定价服务: 装配日历 + 已实现行情, 调用定价引擎。供 Celery / inline 复用。"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import psycopg

from . import repositories_otc as rotc
from .quant.otc.pricer import price_deal

logger = logging.getLogger(__name__)


def run_otc_pricing(conn: psycopg.Connection, spec: dict, progress_cb=None) -> dict:
    """spec 为 JSON 安全的定价参数(日期为 iso 字符串)。返回结果字典。"""
    start = date.fromisoformat(str(spec["start_date"])[:10])
    maturity = date.fromisoformat(str(spec["maturity_date"])[:10])
    sym = spec.get("underlying_symbol")
    src = spec.get("underlying_source", "cn_index_em")

    cal = rotc.load_calendar_view(conn, start, maturity)

    market = None
    if sym:
        try:
            val = date.fromisoformat(str(spec.get("valuation_date") or start)[:10])
            end = max(maturity, val, date.today())
            s = rotc.load_close_series(conn, sym, src, start=start - timedelta(days=30), end=end)
            if not s.empty:
                market = s
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载挂钩指数行情失败 %s@%s: %s", sym, src, exc)

    result = price_deal(spec, cal, market=market, progress_cb=progress_cb)
    return result.to_dict()
