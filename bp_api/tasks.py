"""后台任务: 异步回测。"""

from __future__ import annotations

import logging

from . import cache, db, repositories as repo, tasking
from .settings import ApiSettings

logger = logging.getLogger(__name__)


def run_otc_price_background(spec: dict, deal_id: int | None, task_id: str) -> None:
    """场外定价的 BackgroundTasks 降级路径 (无 Celery/Redis 时)。"""
    logger.info("后台 OTC 定价开始 task_id=%s deal_id=%s", task_id, deal_id)
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

        from .otc_service import run_otc_pricing
        with db.get_conn() as conn:
            result = run_otc_pricing(conn, spec, progress_cb=cb)
            if deal_id is not None:
                from . import repositories_otc as rotc
                rotc.save_deal_valuation(conn, deal_id, result, task_id=task_id)
                conn.commit()
            tasking.mark_success(conn, task_id, result)
            conn.commit()
        logger.info("后台 OTC 定价完成 task_id=%s", task_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("后台 OTC 定价失败 task_id=%s", task_id)
        try:
            with db.get_conn() as conn:
                tasking.mark_failed(conn, task_id, str(exc))
                conn.commit()
        except Exception:  # noqa: BLE001
            logger.exception("任务失败状态写入失败 task_id=%s", task_id)


def run_backtest_background(portfolio_id: int, settings: ApiSettings, task_id: str | None = None) -> None:
    """在独立连接上执行回测并落库; 失败时 run_and_save 会将 status 置为 error。"""
    logger.info("后台回测开始 portfolio_id=%s", portfolio_id)
    try:
        with db.get_conn() as conn:
            if task_id:
                tasking.mark_running(conn, task_id, "后台回测开始")
                conn.commit()
            repo.run_and_save(conn, portfolio_id, settings, task_id=task_id)
            if task_id:
                tasking.mark_success(conn, task_id, {"portfolio_id": portfolio_id})
                conn.commit()
            cache.delete_pattern(f"portfolio_result:{portfolio_id}:*")
        logger.info("后台回测完成 portfolio_id=%s", portfolio_id)
    except Exception as exc:  # noqa: BLE001
        if task_id:
            try:
                with db.get_conn() as conn:
                    tasking.mark_failed(conn, task_id, str(exc))
                    conn.commit()
            except Exception:  # noqa: BLE001
                logger.exception("任务失败状态写入失败 task_id=%s", task_id)
        logger.exception("后台回测失败 portfolio_id=%s", portfolio_id)
