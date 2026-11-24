"""旧链落地后的清洗/状态刷新钩子（P2 收尾）。

旧行情链迁入 bp_etl 后，旧 `bp_quote_clean` 的增量刷新不再由 bp_ingest 调度器驱动，
改由 legacy_index 波次成功后在同一连接上触发：
- 用 DB 交易日历（避免 akshare 新浪日历在限流时挂起）；
- 只刷新旧链配置（`managed_by IS NULL`）涉及的标的；
- 失败只告警，不阻断 ETL 常驻循环。
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


class DbTradingCalendar:
    """最小 TradingCalendar 兼容实现：日期全部来自 bp_trading_calendar。"""

    def __init__(self, conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cal_date FROM bp_trading_calendar"
                " WHERE market='CN' AND is_trading ORDER BY cal_date"
            )
            self._dates = [row[0] for row in cur.fetchall()]
        self._set = set(self._dates)

    @property
    def dates(self) -> list:
        return self._dates

    def is_trading_day(self, day: Any) -> bool:
        return day in self._set

    def trading_days_between(self, start: Any, end: Any) -> list:
        return [day for day in self._dates if start <= day <= end]

    def latest_trading_day_on_or_before(self, day: Any):
        for candidate in reversed(self._dates):
            if candidate <= day:
                return candidate
        return None


def legacy_symbols(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM bp_index_config"
            " WHERE is_deleted=0 AND managed_by IS NULL ORDER BY symbol"
        )
        return [row[0] for row in cur.fetchall()]


def refresh_legacy_clean(conn: Any, symbols: Iterable[str] | None = None) -> dict:
    """重建旧链标的的 bp_quote_clean，并刷新资产状态（COUNT 热路径不带计数）。"""
    from bp_api.quant.cleaning import rebuild_clean  # 惰性导入（pandas 重）

    target = list(symbols) if symbols is not None else legacy_symbols(conn)
    if not target:
        return {"symbols": 0, "written": 0, "status": "skip"}
    cal = DbTradingCalendar(conn)
    written = rebuild_clean(conn, symbols=target, cal=cal)  # type: ignore[arg-type]
    conn.commit()
    status_rows = 0
    try:
        from bp_api.daily_update import refresh_all_asset_status

        status_rows = refresh_all_asset_status(conn, with_count=False)
        conn.commit()
    except Exception:  # noqa: BLE001 - 状态刷新失败不影响清洗结果
        logger.warning("旧链刷新后更新资产状态失败", exc_info=True)
    logger.info("旧链清洗刷新完成: symbols=%d written=%d status_rows=%s", len(target), written, status_rows)
    return {"symbols": len(target), "written": written, "status_rows": status_rows, "status": "ok"}
