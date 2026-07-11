"""Celery 应用配置。"""

from __future__ import annotations

import logging
import os

from celery import Celery
from celery.signals import worker_process_init

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
logger = logging.getLogger(__name__)

celery_app = Celery(
    "balanced_portfolio",
    broker=os.getenv("CELERY_BROKER_URL", REDIS_URL),
    backend=os.getenv("CELERY_RESULT_BACKEND", REDIS_URL),
    include=["bp_api.workers.jobs"],
)


@worker_process_init.connect
def _harden_http_on_worker_start(**_kwargs) -> None:
    """每个 ForkPoolWorker 启动时硬化 HTTP + 预热 EM 代码映射。

    ingest_all 走 Celery 时若不装 curl_cffi 指纹, push2his 会被掐断,
    secid 前缀探测全空 →「无法解析 secid」, 且空表不触发 sina 降级。
    """
    try:
        from bp_ingest.http_session import install_hardened_session
        from bp_ingest.sources import prewarm_em_code_maps

        install_hardened_session()
        prewarm_em_code_maps()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Celery worker HTTP 硬化失败(忽略): %s", exc)


celery_app.conf.update(
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
    # 每 20 分钟巡检: 刷新资产状态 + 排队就绪组合的 T-1 自动更新。
    # 解耦于 bp_ingest 的 6h 调度, 清洗表追赶后能尽快排队。
    beat_schedule={
        "enqueue-ready-every-20m": {
            "task": "bp_api.enqueue_ready",
            "schedule": 1200.0,
        },
        # 每日刷新 A股交易日历(官方段升级 + 未来外推); 交易所公布次年安排后自动 estimated→official。
        "refresh-calendar-weekly": {
            "task": "bp_api.refresh_calendar",
            "schedule": 604800.0,
        },
    },
)

