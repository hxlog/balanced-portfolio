"""任务状态与队列入口。

API 层只负责创建任务并返回 task_id；耗时回测由 Celery worker 执行。
Redis/Celery 不可用时，调用方可以使用 FastAPI BackgroundTasks 作为降级路径。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.types.json import Json


ACTIVE_TASK_STATUSES = ("queued", "running")


def create_task(
    conn: psycopg.Connection,
    task_type: str,
    portfolio_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    progress_total: int = 1,
    message: str = "已加入队列",
) -> str:
    task_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bp_task
                 (task_id, task_type, status, portfolio_id, owner_user_id,
                  progress_current, progress_total, progress_message)
               VALUES (%s,%s,'queued',%s,%s,0,%s,%s)""",
            (task_id, task_type, portfolio_id, owner_user_id, progress_total, message),
        )
    return task_id


def get_task(conn: psycopg.Connection, task_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT task_id, celery_id, task_type, status, portfolio_id, owner_user_id,
                      progress_current, progress_total, progress_message, result, error,
                      created_at, started_at, finished_at
               FROM bp_task WHERE task_id=%s""",
            (task_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"任务不存在: {task_id}")
    def iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    return {
        "task_id": row[0],
        "celery_id": row[1],
        "task_type": row[2],
        "status": row[3],
        "portfolio_id": row[4],
        "owner_user_id": row[5],
        "progress_current": row[6],
        "progress_total": row[7],
        "progress_message": row[8],
        "result": row[9] or {},
        "error": row[10],
        "created_at": iso(row[11]),
        "started_at": iso(row[12]),
        "finished_at": iso(row[13]),
    }


def find_active_portfolio_task(conn: psycopg.Connection, portfolio_id: int) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT task_id FROM bp_task
               WHERE portfolio_id=%s AND status = ANY(%s)
               ORDER BY created_at DESC LIMIT 1""",
            (portfolio_id, list(ACTIVE_TASK_STATUSES)),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_active_portfolio_task(conn: psycopg.Connection, portfolio_id: int) -> Optional[dict]:
    task_id = find_active_portfolio_task(conn, portfolio_id)
    return get_task(conn, task_id) if task_id else None


def set_celery_id(conn: psycopg.Connection, task_id: str, celery_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE bp_task SET celery_id=%s WHERE task_id=%s", (celery_id, task_id))


def mark_running(conn: psycopg.Connection, task_id: str, message: str = "任务开始") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_task SET status='running', started_at=COALESCE(started_at, now()),
                      progress_message=%s
               WHERE task_id=%s""",
            (message, task_id),
        )


def update_progress(
    conn: psycopg.Connection,
    task_id: Optional[str],
    current: int,
    total: int,
    message: str,
) -> None:
    if not task_id:
        return
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_task
               SET progress_current=%s, progress_total=%s, progress_message=%s
               WHERE task_id=%s""",
            (current, total, message, task_id),
        )


def mark_success(conn: psycopg.Connection, task_id: str, result: Optional[dict[str, Any]] = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_task
               SET status='success', progress_current=progress_total,
                   progress_message='完成', result=%s, error=NULL, finished_at=now()
               WHERE task_id=%s""",
            (Json(result or {}), task_id),
        )


def mark_failed(conn: psycopg.Connection, task_id: str, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_task
               SET status='failed', progress_message='失败', error=%s, finished_at=now()
               WHERE task_id=%s""",
            (error[:2000], task_id),
        )


def enqueue_backtest(task_id: str, portfolio_id: int) -> Optional[str]:
    """提交 Celery 回测任务。失败返回 None，由调用方决定是否降级。"""
    return enqueue_task("bp_api.backtest", {"task_id": task_id, "portfolio_id": portfolio_id})


def enqueue_task(task_name: str, kwargs: dict) -> Optional[str]:
    """提交任意 Celery 任务。BP_TASK_MODE=inline 或 send_task 失败时返回 None，由调用方降级。"""
    if os.getenv("BP_TASK_MODE", "celery").lower() == "inline":
        return None
    try:
        from .workers.celery_app import celery_app

        async_result = celery_app.send_task(task_name, kwargs=kwargs)
        return async_result.id
    except Exception:
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

