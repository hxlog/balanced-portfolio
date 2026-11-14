"""定时调度: 每 BP_SCHEDULE_HOURS 小时(默认 6h)执行一轮增量更新。"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from . import ingest
from .config import AppConfig

logger = logging.getLogger(__name__)


def start(app: AppConfig) -> None:
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    def job() -> None:
        logger.info("===== 定时增量任务开始 =====")
        try:
            ingest.run(app)
        except Exception as exc:  # noqa: BLE001
            logger.exception("定时任务异常: %s", exc)
        logger.info("===== 定时增量任务结束 =====")

    def enqueue_ready_job() -> None:
        """短间隔巡检: 刷新资产状态 + 排队就绪组合的 T-1 自动更新。

        解耦于 6h 增量: 即便本次无新数据, 清洗表追赶后也能尽快排队组合。
        无 Redis/Celery beat 时, 这是组合自动更新的兜底路径。
        """
        try:
            from bp_api.daily_update import enqueue_ready_portfolios, refresh_all_asset_status
            from .db import connect

            with connect(app.db) as conn:
                refresh_all_asset_status(conn)
                queued = enqueue_ready_portfolios(conn)
                conn.commit()
            if queued:
                logger.info("巡检排队 %d 个组合", len(queued))
        except Exception as exc:  # noqa: BLE001
            logger.exception("巡检排队异常: %s", exc)

    def cffex_job() -> None:
        """CFFEX 日行情增量同步: 有新交易日则落库+重算 premium, 否则跳过。"""
        try:
            from . import cffex as _cffex
            from .db import connect

            with connect(app.db) as conn:
                conn.autocommit = False
                stats = _cffex.cffex_sync(conn)
            logger.info("CFFEX 增量同步完成: %s", stats)
        except Exception as exc:  # noqa: BLE001
            logger.exception("CFFEX 增量同步异常: %s", exc)

    def valuation_job() -> None:
        """估值抓取门控：21:00 起每 15 分钟尝试，直到数据完备或达上限。"""
        try:
            from . import valuation_job as _vj

            result = _vj.gate(app)
            logger.info("估值门控结果: %s", result.get("status"))
        except Exception as exc:  # noqa: BLE001
            logger.exception("估值抓取异常: %s", exc)

    def valuation_backfill_job() -> None:
        """次日 09:00 兜底：夜间未完备则再补一次。"""
        try:
            from . import valuation_job as _vj

            _vj.reset_attempts()
            result = _vj.gate(app)
            logger.info("估值兜底结果: %s", result.get("status"))
        except Exception as exc:  # noqa: BLE001
            logger.exception("估值兜底异常: %s", exc)

    def crypto_sync_job() -> None:
        """每日兜底重算 crypto 相关性 (ingest 钩子未覆盖/无新数据时兜底)。

        crypto 日线日更, NYSE 收盘(北京凌晨)后 yfinance 已更新, 故每日 05:30 北京跑。
        27s 全量重算; 不在启动时同步跑(避免阻塞调度器启动), 由首个 05:30 cron 触发。
        """
        try:
            from . import crypto_corr as _cc
            from .db import connect
            from bp_api.crypto import invalidate_crypto_cache

            with connect(app.db) as conn:
                conn.autocommit = False
                stats = _cc.compute_and_store_crypto_corr(conn, full=False)
                conn.commit()
            invalidate_crypto_cache()
            if stats.get("changed"):
                _cc._ping_crypto_revalidate()
            else:
                logger.info("crypto 兜底重算 no-op (effective_td 未推进), 跳过 SSR revalidate")
            logger.info("crypto 兜底重算完成: %s", stats)
        except Exception as exc:  # noqa: BLE001
            logger.exception("crypto 兜底重算异常: %s", exc)

    def crypto_job() -> None:
        """每小时 crypto 增量同步: 拉 6 资产 (yfinance/akshare) → 清洗 → 钩子重算相关性。

        钩子 (ingest.py) 内部按 stats_cc.changed 决定是否 ping SSR revalidate
        (effective_td 未推进则 no-op, 不刷 cacheTag, 与 CFFEX 同语义)。
        NYSE 收盘(北京凌晨)后 yfinance 才更新, 故多数小时为 no-op (源未推进 → skip/stale)。
        与每日 05:30 crypto_sync_job 并存: 05:30 为兜底 (1h 故障/重启错窗补救),
        1h 运行时 05:30 多为 no-op, 二者幂等无冲突。
        不在启动时跑 (避免 6 标的 yfinance + 27s 重算阻塞启动); 首个 tick ~1h 内跑。
        """
        try:
            from . import ingest
            crypto_panel = ["BTC-USD", "DX-Y.NYB", "GC=F", "AU0", "标普500", "纳斯达克"]
            results = ingest.run(app, symbols=crypto_panel, refresh_clean=True)
            logger.info("crypto 小时同步完成: %d 标的", len(results))
        except Exception as exc:  # noqa: BLE001
            logger.exception("crypto 小时同步异常: %s", exc)

    def market_valuation_job() -> None:
        """21:20 全市场估值快照（东财 push2，5 个板块）。"""
        try:
            from .db import connect
            from .market_valuation import compute

            with connect(app.db) as conn:
                conn.autocommit = False
                result = compute(conn)
            logger.info("全市场估值快照完成: %s", result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("全市场估值快照异常: %s", exc)

    def csindex_value_job() -> None:
        """21:40 中证官网第二口径（官方估值文件，滚动 20 日）。"""
        try:
            from .csindex_value import run as run_csindex
            from .db import connect

            with connect(app.db) as conn:
                conn.autocommit = False
                result = run_csindex(conn)
            logger.info("中证官网口径同步完成: %s", result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("中证官网口径同步异常: %s", exc)

    # 注意: 勿传 next_run_time=None — APScheduler 会将其视为 paused, 周期永不触发。
    # 启动立即执行由下方 job()/cffex_job() 负责; interval 从 start() 后按间隔调度。
    scheduler.add_job(valuation_job, "cron", hour="21-23", minute="*/15", id="valuation")
    scheduler.add_job(valuation_backfill_job, "cron", hour="9", minute="0", id="valuation-backfill")
    scheduler.add_job(market_valuation_job, "cron", hour="21", minute="20", id="market-valuation")
    scheduler.add_job(csindex_value_job, "cron", hour="21", minute="40", id="csindex-value")
    scheduler.add_job(
        job,
        "interval",
        hours=app.schedule_hours,
        id="bp_incremental",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_ready_job,
        "interval",
        minutes=20,
        id="bp_enqueue_ready",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        cffex_job,
        "interval",
        hours=app.cffex_sync_hours,
        id="bp_cffex_sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        crypto_sync_job,
        "cron",
        hour=5,
        minute=30,
        timezone="Asia/Shanghai",
        id="bp_crypto_sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        crypto_job,
        "interval",
        hours=app.crypto_sync_hours,
        id="bp_crypto_sync_hourly",
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "调度器启动: 每 %d 小时增量更新 + 每 20 分钟巡检排队 + 每 %d 小时 CFFEX 增量 + 每 %d 小时 crypto 增量 + 每日 05:30 北京 crypto 兜底重算",
        app.schedule_hours, app.cffex_sync_hours, app.crypto_sync_hours,
    )
    # 启动即先跑一轮, 再进入周期调度
    job()
    cffex_job()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器停止")
