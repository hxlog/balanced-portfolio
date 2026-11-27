"""运行/源健康/质量问题/backlog 落库。

设计 §5。所有写入幂等；失败不阻断 ETL 主流程（调用方捕获并记日志）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Sequence

from bp_etl.quality import QualityIssue


@dataclass
class RunRecord:
    dataset: str
    trade_date: date
    wave: int
    status: str  # running / ok / catching_up / error
    target_coverage: float | None = None
    achieved_coverage: float | None = None
    rows_written: int = 0
    sources_used: dict[str, Any] = field(default_factory=dict)
    errors: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


def start_run(conn, record: RunRecord) -> int:
    sql = (
        "INSERT INTO bp_etl_run (dataset, trade_date, wave, status, target_coverage,"
        " achieved_coverage, rows_written, sources_used, errors, detail)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING run_id"
    )
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record.dataset, record.trade_date, record.wave, record.status,
                record.target_coverage, record.achieved_coverage, record.rows_written,
                json.dumps(record.sources_used, ensure_ascii=False, default=str),
                record.errors, json.dumps(record.detail, ensure_ascii=False, default=str),
            ),
        )
        row = cur.fetchone()
    return int(row[0])


def finish_run(
    conn, run_id: int, record: RunRecord, *, status: str | None = None
) -> None:
    sql = (
        "UPDATE bp_etl_run SET status=%s, achieved_coverage=%s, rows_written=%s,"
        " errors=%s, detail=%s, finished_at=now() WHERE run_id=%s"
    )
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                status or record.status, record.achieved_coverage, record.rows_written,
                record.errors, json.dumps(record.detail, ensure_ascii=False, default=str),
                run_id,
            ),
        )


def record_source_health(
    conn,
    *,
    stat_date: date,
    dataset: str,
    source: str,
    channel: str,
    snapshot: dict[str, Any],
    coverage_today: float | None = None,
) -> None:
    sql = (
        "INSERT INTO bp_etl_source_health (stat_date, dataset, source, channel, attempts,"
        " ok, failed, banned_count, avg_latency_ms, p95_latency_ms, coverage_today)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (stat_date, dataset, source, channel) DO UPDATE SET"
        " attempts=EXCLUDED.attempts, ok=EXCLUDED.ok, failed=EXCLUDED.failed,"
        " banned_count=EXCLUDED.banned_count, avg_latency_ms=EXCLUDED.avg_latency_ms,"
        " p95_latency_ms=EXCLUDED.p95_latency_ms,"
        " coverage_today=COALESCE(EXCLUDED.coverage_today, bp_etl_source_health.coverage_today),"
        " updated_at=now()"
    )
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                stat_date, dataset, source, channel,
                int(snapshot.get("attempts") or 0),
                int(snapshot.get("ok") or 0),
                int(snapshot.get("failed") or 0),
                int(snapshot.get("banned_count") or 0),
                snapshot.get("avg_latency_ms"),
                snapshot.get("p95_latency_ms"),
                coverage_today,
            ),
        )


def record_issues(conn, issues: Sequence[QualityIssue]) -> int:
    if not issues:
        return 0
    sql = (
        "INSERT INTO bp_etl_quality_issue (dataset, symbol, trade_date, kind, severity, detail)"
        " VALUES (%s, %s, %s, %s, %s, %s)"
    )
    payload = [
        (
            issue.dataset, issue.symbol, issue.trade_date, issue.kind, issue.severity,
            json.dumps(issue.detail, ensure_ascii=False, default=str),
        )
        for issue in issues
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, payload)
    return len(payload)


def upsert_dataset_state(
    conn, dataset: str, adjust: str, last_success_date: date | None, run_id: int | None
) -> None:
    sql = (
        "INSERT INTO bp_etl_dataset_state (dataset, adjust, last_success_date, last_run_id)"
        " VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (dataset, adjust) DO UPDATE SET"
        " last_success_date=GREATEST("
        "   COALESCE(bp_etl_dataset_state.last_success_date, EXCLUDED.last_success_date),"
        "   COALESCE(EXCLUDED.last_success_date, bp_etl_dataset_state.last_success_date)),"
        " last_run_id=COALESCE(EXCLUDED.last_run_id, bp_etl_dataset_state.last_run_id),"
        " updated_at=now()"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (dataset, adjust, last_success_date, run_id))


def upsert_backlog(
    conn,
    *,
    dataset: str,
    trade_date: date,
    adjust: str,
    symbols: Sequence[str],
    reason: str,
    next_retry_at: datetime,
) -> int:
    if not symbols:
        return 0
    sql = (
        "INSERT INTO bp_etl_backlog (dataset, trade_date, adjust, scope, symbol, reason, attempts, next_retry_at)"
        " VALUES (%s, %s, %s, 'symbol', %s, %s, 0, %s)"
        " ON CONFLICT (dataset, trade_date, adjust, scope, symbol) DO UPDATE SET"
        " reason=EXCLUDED.reason, attempts=bp_etl_backlog.attempts + 1,"
        " next_retry_at=EXCLUDED.next_retry_at, updated_at=now()"
    )
    payload = [(dataset, trade_date, adjust, symbol, reason, next_retry_at) for symbol in symbols]
    with conn.cursor() as cur:
        cur.executemany(sql, payload)
    return len(payload)


def due_backlog(
    conn, dataset: str, adjust: str, now: datetime, *, limit: int = 5000
) -> list[str]:
    sql = (
        "SELECT symbol FROM bp_etl_backlog"
        " WHERE dataset=%s AND adjust=%s AND next_retry_at <= %s"
        " ORDER BY next_retry_at LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (dataset, adjust, now, limit))
        return [row[0] for row in cur.fetchall()]


def due_backlog_dates(
    conn, dataset: str, adjust: str, now: datetime, *, limit: int = 10
) -> list[date]:
    """到期待重试的 backlog 交易日（跨日续跑必须以 backlog 自身日期重放，不能用"当前"日期）。"""
    sql = (
        "SELECT trade_date, min(next_retry_at) FROM bp_etl_backlog"
        " WHERE dataset=%s AND adjust=%s AND next_retry_at <= %s"
        " GROUP BY trade_date ORDER BY min(next_retry_at), trade_date LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (dataset, adjust, now, limit))
        return [row[0] for row in cur.fetchall()]


def clear_backlog(
    conn,
    dataset: str,
    trade_date: date,
    adjust: str,
    symbols: Sequence[str] | None = None,
) -> int:
    if symbols is None:
        sql = "DELETE FROM bp_etl_backlog WHERE dataset=%s AND trade_date=%s AND adjust=%s"
        params: tuple = (dataset, trade_date, adjust)
    else:
        if not symbols:
            return 0
        sql = (
            "DELETE FROM bp_etl_backlog WHERE dataset=%s AND trade_date=%s AND adjust=%s"
            " AND scope='symbol' AND symbol = ANY(%s)"
        )
        params = (dataset, trade_date, adjust, list(symbols))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# backlog 对账/清理（旧 universe 的历史空转条目收敛）
# ---------------------------------------------------------------------------
def prune_backlog_symbols(
    conn,
    dataset: str,
    adjust: str,
    keep_symbols: Sequence[str],
    *,
    trade_date: date | None = None,
) -> int:
    """删除 backlog 中不在当前 universe 的 symbol 行（旧 universe 遗留条目）。

    背景：legacy 旧链 universe 经历过口径收敛（9,600 -> ~747 可交易），
    旧 universe 的 backlog symbol 行永远不会被重放，导致 backlog 长期 >30k 且
    每小时空转。对账时以**当前 universe** 为准，把这些行直接收敛掉。

    keep_symbols 为空表示当前 universe 为空（异常态）：此时不删除任何行，返回 0，
    避免把 backlog 全清了却无任何数据。
    返回删除行数。
    """
    keep = list(dict.fromkeys(keep_symbols))
    if not keep:
        return 0
    sql = (
        "DELETE FROM bp_etl_backlog WHERE dataset=%s AND adjust=%s"
        " AND scope='symbol' AND NOT (symbol = ANY(%s))"
    )
    params: list = [dataset, adjust, keep]
    if trade_date is not None:
        sql += " AND trade_date = %s"
        params.append(trade_date)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return int(cur.rowcount or 0)


def purge_backlog_dates(
    conn,
    dataset: str,
    adjust: str,
    trade_dates: Sequence[date],
) -> int:
    """按日期整批删除 backlog（一次性清理旧口径历史条目用；调用方需先 dry-run）。"""
    dates = list(dict.fromkeys(trade_dates))
    if not dates:
        return 0
    sql = (
        "DELETE FROM bp_etl_backlog WHERE dataset=%s AND adjust=%s"
        " AND trade_date = ANY(%s)"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (dataset, adjust, dates))
        return int(cur.rowcount or 0)


def purge_backlog_before(
    conn,
    dataset: str,
    adjust: str,
    before_date: date,
) -> int:
    """删除早于 before_date 的 backlog（超期历史日期，避免永久卡住当日 SLA）。"""
    sql = (
        "DELETE FROM bp_etl_backlog WHERE dataset=%s AND adjust=%s"
        " AND trade_date < %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (dataset, adjust, before_date))
        return int(cur.rowcount or 0)


def backlog_summary(
    conn, dataset: str | None = None, adjust: str | None = None
) -> list[dict]:
    """backlog 分布（供 CLI/巡检脚本输出；只读）。"""
    sql = (
        "SELECT dataset, adjust, trade_date, count(*) AS pending,"
        " count(*) FILTER (WHERE scope='dataset') AS dataset_scope"
        " FROM bp_etl_backlog"
    )
    params: list = []
    conditions: list[str] = []
    if dataset:
        conditions.append("dataset = %s")
        params.append(dataset)
    if adjust:
        conditions.append("adjust = %s")
        params.append(adjust)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " GROUP BY dataset, adjust, trade_date ORDER BY trade_date DESC, dataset, adjust"
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return [
            {
                "dataset": row[0],
                "adjust": row[1],
                "trade_date": row[2],
                "pending": int(row[3]),
                "dataset_scope": int(row[4]),
            }
            for row in cur.fetchall()
        ]
