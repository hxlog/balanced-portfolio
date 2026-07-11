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

    scheduler.add_job(
        job,
        "interval",
        hours=app.schedule_hours,
        id="bp_incremental",
        next_run_time=None,  # 不在启动时立即执行(由 CLI --run-now 控制)
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_ready_job,
        "interval",
        minutes=20,
        id="bp_enqueue_ready",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        cffex_job,
        "interval",
        hours=app.cffex_sync_hours,
        id="bp_cffex_sync",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "调度器启动: 每 %d 小时增量更新 + 每 20 分钟巡检排队组合 + 每 %d 小时 CFFEX 增量",
        app.schedule_hours, app.cffex_sync_hours,
    )
    # 启动即先跑一轮, 再进入周期调度
    job()
    cffex_job()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器停止")
