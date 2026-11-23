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