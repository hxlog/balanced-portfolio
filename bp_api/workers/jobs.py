"""Celery worker jobs."""

from __future__ import annotations

import logging

from bp_api import cache, db, repositories as repo, tasking
from bp_api.settings import load_settings
from bp_api.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="bp_api.backtest", bind=True, max_retries=1)
def run_backtest_job(self, task_id: str, portfolio_id: int) -> dict:
    settings = load_settings()
    db.init_pool(settings)
    logger.info("Celery 回测开始 task_id=%s portfolio_id=%s", task_id, portfolio_id)
    try:
        with db.get_conn() as conn:
            tasking.mark_running(conn, task_id, "正在加载行情与组合参数")
            conn.commit()
            repo.run_and_save(conn, portfolio_id, settings, task_id=task_id)
            tasking.mark_success(conn, task_id, {"portfolio_id": portfolio_id})
            conn.commit()
        cache.delete_pattern(f"portfolio_result:{portfolio_id}:*")
        logger.info("Celery 回测完成 task_id=%s portfolio_id=%s", task_id, portfolio_id)
        return {"portfolio_id": portfolio_id, "task_id": task_id}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Celery 回测失败 task_id=%s portfolio_id=%s", task_id, portfolio_id)
        with db.get_conn() as conn:
            tasking.mark_failed(conn, task_id, str(exc))
            conn.commit()
        raise


@celery_app.task(name="bp_api.ingest_all", bind=True, max_retries=1)
def run_ingest_all_job(self, task_id: str) -> dict:
    """全量增量行情拉取 + 清洗 + 组合自动排队更新。"""
    settings = load_settings()
    db.init_pool(settings)
    logger.info("Celery 全量拉取开始 task_id=%s", task_id)
    try:
        from bp_ingest.config import load_config as load_ingest_config
        from bp_ingest import ingest as bp_ingest_run
        from bp_ingest.http_session import install_hardened_session
        from bp_ingest.sources import prewarm_em_code_maps

        # 幂等; worker_process_init 已装过则直接返回。兜底: 热重载/非 prefork 池。
        install_hardened_session()
        prewarm_em_code_maps()

        with db.get_conn() as conn:
            tasking.mark_running(conn, task_id, "步骤 1/3：拉取全量增量行情")
            conn.commit()
        app_cfg = load_ingest_config()
        results = bp_ingest_run.run(app_cfg, symbols=None, refresh_clean=True)
        # ingest.run 内部已刷新清洗表并调用 enqueue_ready_portfolios。
        with db.get_conn() as conn:
            tasking.update_progress(conn, task_id, 3, 3, "全量拉取完成")
            tasking.mark_success(conn, task_id, {"symbols": len(results)})
            conn.commit()
        logger.info("Celery 全量拉取完成 task_id=%s", task_id)
        return {"task_id": task_id, "symbols": len(results)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Celery 全量拉取失败 task_id=%s", task_id)
        with db.get_conn() as conn:
            tasking.mark_failed(conn, task_id, str(exc))
            conn.commit()
        raise


@celery_app.task(name="bp_api.price_otc", bind=True, max_retries=0)
def run_otc_price_job(self, task_id: str, spec: dict, deal_id: int | None = None) -> dict:
    """场外衍生品异步定价 (含 Greeks)。"""
    settings = load_settings()
    db.init_pool(settings)
    logger.info("Celery OTC 定价开始 task_id=%s deal_id=%s", task_id, deal_id)
    try:
        with db.get_conn() as conn:
            tasking.mark_running(conn, task_id, "开始定价")
            conn.commit()

        def cb(cur: int, total: int, msg: str) -> None:
            try:
                with db.get_conn() as c2:
                    tasking.update_progress(c2, task_id, cur, total, msg)
                    c2.commit()
            except Exception:  # noqa: BLE001
                pass

        from bp_api.otc_service import run_otc_pricing
        with db.get_conn() as conn:
            result = run_otc_pricing(conn, spec, progress_cb=cb)
            if deal_id is not None:
                from bp_api import repositories_otc as rotc
                rotc.save_deal_valuation(conn, deal_id, result, task_id=task_id)
                conn.commit()
            tasking.mark_success(conn, task_id, result)
            conn.commit()
        logger.info("Celery OTC 定价完成 task_id=%s", task_id)
        return {"task_id": task_id}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Celery OTC 定价失败 task_id=%s", task_id)
        with db.get_conn() as conn:
            tasking.mark_failed(conn, task_id, str(exc))
            conn.commit()
        raise


@celery_app.task(name="bp_api.refresh_calendar")
def run_refresh_calendar() -> dict:
    """定时刷新 A股交易日历 (官方段 + 未来外推)。"""
    settings = load_settings()
    db.init_pool(settings)
    from bp_api import repositories_otc as rotc
    try:
        with db.get_conn() as conn:
            info = rotc.refresh_trading_calendar(conn)
            conn.commit()
        logger.info("交易日历定时刷新完成: %s", info)
        return info
    except Exception:  # noqa: BLE001
        logger.exception("交易日历定时刷新失败")
        raise


@celery_app.task(name="bp_api.enqueue_ready")
def run_enqueue_ready() -> dict:
    """定时(beat)巡检: 刷新资产状态 + 排队就绪组合的 T-1 自动更新。

    解耦于 bp_ingest 的 6h 调度, 使组合能在清洗表追赶后尽快被排队。
    """
    settings = load_settings()
    db.init_pool(settings)
    from bp_api.daily_update import enqueue_ready_portfolios, refresh_all_asset_status

    try:
        with db.get_conn() as conn:
            refresh_all_asset_status(conn)
            queued = enqueue_ready_portfolios(conn)
            conn.commit()
        logger.info("beat 巡检完成, 排队 %d 个组合", len(queued))
        return {"queued": len(queued)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("beat enqueue_ready 失败")
        raise

