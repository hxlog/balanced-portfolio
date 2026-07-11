"""行情刷新后的 T-1 portfolio 自动更新编排。"""

from __future__ import annotations

import logging

import psycopg

from . import repositories as repo, tasking

logger = logging.getLogger(__name__)


def refresh_all_asset_status(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, source FROM bp_index_config WHERE is_deleted = 0")
        pairs = cur.fetchall()
    for symbol, source in pairs:
        repo.refresh_asset_status(conn, symbol, source)


def enqueue_ready_portfolios(conn: psycopg.Connection) -> list[dict]:
    """每组合排队更新到"该组合所有成分都有完整行情的那一天"。

    target_per_portfolio = MIN(各成分 last_clean_date)。
    - 任一成分无清洗数据(min_clean IS NULL) → 跳过(数据未到齐)。
    - result_date >= min_clean → 跳过(已更新到该日)。
    - 否则排队回测; 回测引擎(load_price_panel)会截断面板到 min last_valid, nav 止于该日。
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.portfolio_id, p.owner_user_id,
                      COALESCE(st.last_result_trade_date, p.data_as_of_date) AS result_date,
                      mins.min_clean
               FROM bp_portfolio p
               LEFT JOIN bp_portfolio_update_state st ON st.portfolio_id = p.portfolio_id
               LEFT JOIN LATERAL (
                   SELECT MIN(s.last_clean_date) AS min_clean
                   FROM (
                       SELECT DISTINCT symbol, source
                       FROM bp_portfolio_asset
                       WHERE portfolio_id = p.portfolio_id
                   ) a
                   LEFT JOIN bp_asset_data_status s
                     ON s.symbol = a.symbol AND s.source = a.source
               ) mins ON true
               WHERE p.status <> 'running'
               ORDER BY p.portfolio_id"""
        )
        portfolios = cur.fetchall()

    enqueued: list[dict] = []
    skipped: list[dict] = []
    for pid, owner_user_id, result_date, min_clean in portfolios:
        if min_clean is None:
            skipped.append({"portfolio_id": pid, "reason": "成分无清洗数据"})
            continue
        if result_date is not None and result_date >= min_clean:
            skipped.append({"portfolio_id": pid, "already_at": result_date, "min_clean": min_clean})
            continue
        active = tasking.find_active_portfolio_task(conn, pid)
        if active:
            skipped.append({"portfolio_id": pid, "active_task": active})
            continue
        task_id = tasking.create_task(
            conn,
            "daily_update",
            portfolio_id=pid,
            owner_user_id=owner_user_id,
            progress_total=6,
            message=f"行情已更新至 {min_clean}, 等待自动回测",
        )
        celery_id = tasking.enqueue_backtest(task_id, pid)
        if celery_id:
            tasking.set_celery_id(conn, task_id, celery_id)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bp_portfolio SET status='running', error=NULL WHERE portfolio_id=%s",
                (pid,),
            )
        enqueued.append({"portfolio_id": pid, "task_id": task_id, "target_trade_date": min_clean})

    logger.info(
        "自动更新 portfolio: 排队=%d 跳过=%d 跳过详情=%s",
        len(enqueued), len(skipped), skipped,
    )
    return enqueued

