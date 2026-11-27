"""管理端数据健康 API（仅超级管理员）：ETL 就绪状态/运行记录/源健康/质量问题 + 手动重放。

只读查询 + 手动重放（后台任务）。页面：/admin/market-data。
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Query
from pydantic import BaseModel

from . import auth, db

logger = logging.getLogger(__name__)

DATASET_NAMES = ("a_stock", "hk_stock", "etf", "fund_nav")
_COVERAGE_KIND = {"a_stock": "stock", "hk_stock": "stock", "etf": "etf", "fund_nav": "fund"}


class ReplayIn(BaseModel):
    dataset: str
    date: Optional[str] = None
    adjust: Optional[str] = None


def _iso(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _latest_trading_date(conn: Any) -> Optional[dt.date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(cal_date) FROM bp_trading_calendar"
            " WHERE market='CN' AND is_trading AND cal_date <= current_date"
        )
        row = cur.fetchone()
    return row[0] if row else None


def _dataset_overview(conn: Any, latest: dt.date | None) -> list[dict[str, Any]]:
    states: dict[str, Any] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT dataset, last_success_date, last_run_id, updated_at FROM bp_etl_dataset_state")
        for name, last_success, run_id, updated in cur.fetchall():
            states[name] = {"last_success_date": last_success, "last_run_id": run_id, "updated_at": updated}
    backlog: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT dataset, count(*) FROM bp_etl_backlog GROUP BY dataset")
        for name, count in cur.fetchall():
            backlog[name] = int(count)
    last_runs: dict[str, dict[str, Any]] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (dataset) dataset, run_id, trade_date, wave, status,"
            " achieved_coverage, finished_at FROM bp_etl_run"
            " ORDER BY dataset, run_id DESC"
        )
        for name, run_id, trade_date, wave, status, coverage, finished in cur.fetchall():
            last_runs[name] = {
                "run_id": run_id, "trade_date": trade_date, "wave": wave,
                "status": status, "achieved_coverage": coverage, "finished_at": finished,
            }
    items: list[dict[str, Any]] = []
    for name in DATASET_NAMES:
        state = states.get(name, {})
        last_success = state.get("last_success_date")
        ready = bool(latest and last_success and last_success >= latest)
        items.append(
            {
                "dataset": name,
                "coverage_kind": _COVERAGE_KIND[name],
                "latest_trading_date": latest,
                "last_success_date": last_success,
                "ready": ready,
                "backlog": backlog.get(name, 0),
                "last_run": last_runs.get(name),
                "state_updated_at": state.get("updated_at"),
            }
        )
    return items


def _coverage_counts(conn: Any, latest: dt.date | None) -> dict[str, Any]:
    """当日覆盖快照计数（分子）；分母取主数据规模（分母在页面展示为参考）。"""
    if latest is None:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE last_date >= %s AND length(code) = 6),"
            " count(*) FILTER (WHERE last_date >= %s AND length(code) = 5)"
            " FROM bp_asset_coverage WHERE kind = 'stock'",
            (latest, latest),
        )
        a_ok, hk_ok = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM bp_asset_coverage WHERE kind='etf' AND last_date >= %s", (latest,)
        )
        etf_ok = cur.fetchone()[0]
        cur.execute(
            "SELECT count(DISTINCT fund_code) FROM bp_fund_nav_daily WHERE trade_date = %s", (latest,)
        )
        fund_ok = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM bp_stock_master WHERE market IN ('SH','SZ','BJ') AND is_delisted=FALSE"
        )
        a_total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM bp_stock_master WHERE market='HK' AND is_delisted=FALSE")
        hk_total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM bp_etf_master")
        etf_total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM bp_fund_master")
        fund_total = cur.fetchone()[0]
    return {
        "a_stock": {"covered": int(a_ok or 0), "total": int(a_total or 0)},
        "hk_stock": {"covered": int(hk_ok or 0), "total": int(hk_total or 0)},
        "etf": {"covered": int(etf_ok or 0), "total": int(etf_total or 0)},
        "fund_nav": {"covered": int(fund_ok or 0), "total": int(fund_total or 0)},
    }


def _run_replay(dataset: str, trade_date: Optional[str], adjust: Optional[str]) -> None:
    """后台重放一个波次（管理端手动触发；失败只记日志，不阻塞请求）。"""
    try:
        from datetime import date as _date

        from bp_etl.cli import load_etl_config
        from bp_etl.datasets import get_runners
        from bp_etl.orchestrator import Orchestrator

        config = load_etl_config()
        orchestrator = Orchestrator(config, runners=get_runners(config))
        runner = orchestrator.runners[dataset]
        keys = ("nav",) if runner.spec.value_kind == "nav" else runner.spec.adjust_modes
        targets = [adjust] if adjust else list(keys)
        parsed = _date.fromisoformat(trade_date) if trade_date else None
        for key in targets:
            result = orchestrator.run_wave(dataset, key, trade_date=parsed, wave=1, force=True)
            logger.info("管理端重放 %s/%s -> ok=%s coverage=%s", dataset, key, result.ok, result.coverage)
    except Exception:  # noqa: BLE001 - 后台任务异常不得影响 API 进程
        logger.exception("管理端重放失败 dataset=%s", dataset)


def register_routes(app: FastAPI) -> None:
    @app.get("/api/admin/data-health/overview")
    def data_health_overview(_user: auth.UserContext = Depends(auth.require_super_admin)) -> dict:
        with db.get_conn() as conn:
            latest = _latest_trading_date(conn)
            datasets = _dataset_overview(conn, latest)
            coverage = _coverage_counts(conn, latest)
        for item in datasets:
            item["coverage"] = coverage.get(item["dataset"])
        return {
            "data": {
                "datasets": datasets,
                "latest_trading_date": _iso(latest),
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            "meta": {"mode": "etl"},
            "error": None,
        }

    @app.get("/api/admin/data-health/runs")
    def data_health_runs(
        dataset: Optional[str] = Query(None),
        limit: int = Query(20, ge=1, le=200),
        _user: auth.UserContext = Depends(auth.require_super_admin),
    ) -> dict:
        sql = (
            "SELECT run_id, dataset, trade_date, wave, status, target_coverage,"
            " achieved_coverage, rows_written, errors, started_at, finished_at"
            " FROM bp_etl_run"
        )
        params: list[Any] = []
        if dataset:
            sql += " WHERE dataset = %s"
            params.append(dataset)
        sql += " ORDER BY run_id DESC LIMIT %s"
        params.append(limit)
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc.name for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {"data": [{k: _iso(v) for k, v in row.items()} for row in rows], "meta": {}, "error": None}

    @app.get("/api/admin/data-health/sources")
    def data_health_sources(
        days: int = Query(7, ge=1, le=90),
        _user: auth.UserContext = Depends(auth.require_super_admin),
    ) -> dict:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT stat_date, dataset, source, channel, attempts, ok, failed,"
                " banned_count, avg_latency_ms, p95_latency_ms, coverage_today"
                " FROM bp_etl_source_health"
                " WHERE stat_date >= current_date - %s ORDER BY stat_date DESC, dataset, source",
                (days,),
            )
            columns = [desc.name for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {"data": [{k: _iso(v) for k, v in row.items()} for row in rows], "meta": {}, "error": None}

    @app.get("/api/admin/data-health/issues")
    def data_health_issues(
        dataset: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=500),
        _user: auth.UserContext = Depends(auth.require_super_admin),
    ) -> dict:
        sql = (
            "SELECT issue_id, dataset, symbol, trade_date, kind, severity, detail, created_at"
            " FROM bp_etl_quality_issue WHERE resolved_at IS NULL"
        )
        params: list[Any] = []
        if dataset:
            sql += " AND dataset = %s"
            params.append(dataset)
        sql += " ORDER BY issue_id DESC LIMIT %s"
        params.append(limit)
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc.name for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {"data": [{k: _iso(v) for k, v in row.items()} for row in rows], "meta": {}, "error": None}

    @app.post("/api/admin/data-health/replay")
    def data_health_replay(
        payload: ReplayIn,
        background: BackgroundTasks,
        _user: auth.UserContext = Depends(auth.require_super_admin),
    ) -> dict:
        from bp_etl.registry import REGISTRY

        if payload.dataset not in REGISTRY:
            return {"data": None, "meta": {}, "error": {"code": "invalid_dataset", "message": payload.dataset}}
        background.add_task(_run_replay, payload.dataset, payload.date, payload.adjust)
        return {"data": {"accepted": True, "dataset": payload.dataset}, "meta": {}, "error": None}

    # ------------------------------------------------------------------
    # 公开只读：每日 09:30 数据体检结果（scripts/daily_data_audit.py 写入）
    # 与 /api/v1/market/data-freshness 一样匿名可读：全局数据健康状态不是敏感信息。
    # ------------------------------------------------------------------
    @app.get("/api/v1/market/data-health")
    def market_data_health(
        _user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """最近一次每日体检（bp_data_audit_daily）：逐条 metric 的 value/threshold/status。"""
        try:
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT max(stat_date) FROM bp_data_audit_daily")
                row = cur.fetchone()
                stat_date = row[0] if row else None
                checks: list[dict[str, Any]] = []
                if stat_date is not None:
                    cur.execute(
                        "SELECT dataset, metric, value, threshold, status, detail, created_at"
                        " FROM bp_data_audit_daily WHERE stat_date = %s"
                        " ORDER BY dataset, metric",
                        (stat_date,),
                    )
                    columns = [desc.name for desc in cur.description]
                    for record in cur.fetchall():
                        item = dict(zip(columns, record))
                        for key in ("value", "threshold"):
                            item[key] = (
                                float(item[key]) if item.get(key) is not None else None
                            )
                        item["stat_date"] = _iso(stat_date)
                        item["created_at"] = _iso(item.get("created_at"))
                        checks.append(item)
        except Exception:  # noqa: BLE001 - 迁移未应用/表缺失时返回不可用而不是 500
            logger.warning("读取 bp_data_audit_daily 失败（ddl/82 可能未应用）", exc_info=True)
            return {
                "data": None,
                "meta": {"available": False, "reason": "audit_table_unavailable"},
                "error": None,
            }
        summary = {
            "ok": sum(1 for item in checks if item.get("status") == "ok"),
            "warn": sum(1 for item in checks if item.get("status") == "warn"),
            "error": sum(1 for item in checks if item.get("status") == "error"),
            "total": len(checks),
        }
        return {
            "data": {
                "stat_date": _iso(stat_date) if stat_date is not None else None,
                "checks": checks,
            },
            "meta": {
                "available": stat_date is not None,
                "summary": summary,
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            "error": None,
        }
