"""估值抓取的调度门控：每日 21:00 起，未完备则每 15 分钟重试，直到新数据齐全。

用户需求（D65）：抓取后要校验是否已更新到「理论最新交易日」；未完备则每 15 分钟重试一次，
直到完备或达到上限后告警。判据：is_tracked 指数当日主口径覆盖率 >= 99%。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import AppConfig
from .db import connect
from .valuation_ingest import FALLBACK_INDEX_CODES, run_valuation_ingest

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Shanghai")
CLOSE_CONFIRM_HHMM = (15, 10)  # 与行情收盘确认口径一致
COVERAGE_TARGET = 0.99
RETRY_LIMIT = 8  # 21:00 起最多 8 次（2 小时）

_attempts: dict[date, int] = {}


def theoretical_latest_trade_date(conn, now: datetime | None = None) -> date | None:
    """理论最新交易日：已收盘确认的最近一个 A 股交易日。"""
    now = now or datetime.now(TZ)
    if (now.hour, now.minute) >= CLOSE_CONFIRM_HHMM:
        cutoff = now.date()
    else:
        cutoff = now.date() - timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(cal_date) FROM bp_trading_calendar WHERE is_trading AND cal_date <= %s",
            (cutoff,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def coverage(conn, as_of: date) -> tuple[int, int, bool]:
    """(已有主口径的跟踪指数数, 跟踪指数总数, fallback 指数是否缺当日数据)。

    平安估值 universe 不覆盖的 fallback 指数（中证全指 000985 等）不参与 521 只的
    is_tracked 主口径覆盖率，单独判定：只要它在 master 里 is_tracked 但当日没有
    主口径行，门控就视为未完备，触发下一轮抓取（由 valuation_ingest 的中证官网
    fallback 补数），否则 521/522 已 >= 99% 会让门控提前跳过、000985 永远补不上。
    """
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM bp_index_master WHERE is_tracked")
        total = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT count(DISTINCT d.index_code)
            FROM bp_index_valuation_daily d
            JOIN bp_index_master m USING (index_code)
            WHERE m.is_tracked AND d.trade_date = %s AND d.is_primary
            """,
            (as_of,),
        )
        done = int(cur.fetchone()[0])
        cur.execute(
            "SELECT index_code FROM bp_index_master"
            " WHERE is_tracked AND index_code = ANY(%s)",
            (list(FALLBACK_INDEX_CODES),),
        )
        required = [row[0] for row in cur.fetchall()]
        fallback_missing = False
        if required:
            cur.execute(
                "SELECT count(DISTINCT index_code) FROM bp_index_valuation_daily"
                " WHERE trade_date = %s AND is_primary AND index_code = ANY(%s)",
                (as_of, required),
            )
            fallback_missing = int(cur.fetchone()[0]) < len(required)
    return done, total, fallback_missing


def gate(app: AppConfig, now: datetime | None = None) -> dict:
    """一次门控尝试：完备则跳过；未完备且未达上限则抓一轮。"""
    now = now or datetime.now(TZ)
    with connect(app.db) as conn:
        as_of = theoretical_latest_trade_date(conn, now)
        if as_of is None:
            logger.warning("估值门控：无法确定理论最新交易日")
            return {"status": "no_calendar"}
        done, total, fallback_missing = coverage(conn, as_of)
        ratio = (done / total) if total else 0.0
        if total and ratio >= COVERAGE_TARGET and not fallback_missing:
            logger.info("估值门控：%s 已完备 %d/%d (%.1f%%)", as_of, done, total, ratio * 100)
            return {"status": "complete", "as_of": as_of, "done": done, "total": total}

        attempts = _attempts.get(as_of, 0)
        if attempts >= RETRY_LIMIT:
            logger.error(
                "估值门控：%s 连续 %d 次仍未完备 (%d/%d)，转为次日 09:00 兜底",
                as_of, attempts, done, total,
            )
            return {"status": "exhausted", "as_of": as_of, "done": done, "total": total}

        _attempts[as_of] = attempts + 1
        summary = run_valuation_ingest(conn, as_of=as_of)
        conn.commit()
        logger.info("估值门控：第 %d 次抓取完成 %s", attempts + 1, summary)
        return {"status": "ingested", "attempt": attempts + 1, "summary": summary}


def reset_attempts() -> None:
    _attempts.clear()
