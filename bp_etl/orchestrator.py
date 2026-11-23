"""数据集波次编排：收盘确认 → 抓取 → 写库 → 质量门 → 覆盖 → 未达标 backfill。

核心语义（设计与 Q 指示）：
- **无硬停**：单波未达标不终止；按 10→30 分钟退避无限重试（跨交易日由 backlog 续跑），
  直到 `bp_etl_dataset_state.last_success_date` 追平最新确认交易日；
- 目标时点只用于升级告警（管理页红黄绿），不用于停止；
- 幂等：同 dataset 用 Postgres advisory lock 防重入；重复波次 UPSERT 安全；
- 收盘确认：A 15:10 / HK 16:15 / FUND 20:00（CST），未确认不写当日。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence

from bp_etl.channels import ChannelManager
from bp_etl.config import EtlConfig
from bp_etl.health import (
    RunRecord,
    clear_backlog,
    due_backlog,
    finish_run,
    record_issues,
    record_source_health,
    start_run,
    upsert_backlog,
    upsert_dataset_state,
)
from bp_etl.quality import QualityIssue, QualityReport, evaluate, sanitize_bars
from bp_etl.registry import REGISTRY, DatasetSpec
from bp_etl.writer import refresh_coverage, write_bars, write_navs

logger = logging.getLogger(__name__)

CN = timezone(timedelta(hours=8))
CLOSE_TIMES: dict[str, dtime] = {"A": dtime(15, 10), "HK": dtime(16, 15), "FUND": dtime(20, 0)}
RETRY_INITIAL = timedelta(minutes=10)
RETRY_MAX = timedelta(minutes=30)
POLL_SECONDS = 60


class DatasetRunner(Protocol):
    """每个 dataset 的可注入执行器（T10 的 datasets 模块提供）。"""

    spec: DatasetSpec

    def universe(self, conn: Any) -> list[str]: ...

    def fetch(
        self,
        adjust: str,
        codes: Sequence[str],
        trade_date: date,
        channels: ChannelManager,
    ) -> list[Any]: ...


@dataclass
class WaveResult:
    dataset: str
    adjust: str
    trade_date: date
    wave: int = 1
    fetched: int = 0
    written: int = 0
    coverage: float = 0.0
    ok: bool = False
    skipped: bool = False
    skip_reason: str = ""
    issues: list[QualityIssue] = field(default_factory=list)
    next_retry_in: timedelta | None = None


def retry_interval(wave: int) -> timedelta:
    """退避：第 1 波后 10min，之后每波及 +5min，封顶 30min（永不放弃）。"""
    interval = RETRY_INITIAL + timedelta(minutes=5 * max(0, wave - 1))
    return min(interval, RETRY_MAX)


def default_conn_factory(config: EtlConfig) -> Callable[[], Any]:
    from bp_ingest.db import connect

    return lambda: connect(config.db)


def _now_cn() -> datetime:
    return datetime.now(CN)


class Orchestrator:
    def __init__(
        self,
        config: EtlConfig,
        runners: Mapping[str, DatasetRunner] | None = None,
        *,
        conn_factory: Callable[[], Any] | None = None,
        channel_manager: ChannelManager | None = None,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        write_enabled: bool | None = None,
    ) -> None:
        self.config = config
        self.runners: dict[str, DatasetRunner] = dict(runners or {})
        self.channels = channel_manager or ChannelManager(config)
        self._conn_factory = conn_factory or default_conn_factory(config)
        self._now_fn = now_fn or _now_cn
        self._sleep = sleep_fn
        self._write_enabled = config.write_enabled if write_enabled is None else write_enabled
        self._last_retry: dict[tuple[str, str], datetime] = {}

    # -- calendar -----------------------------------------------------
    def latest_trading_day(self, conn: Any, reference: date) -> date | None:
        sql = (
            "SELECT max(cal_date) FROM bp_trading_calendar"
            " WHERE market = 'CN' AND is_trading AND cal_date <= %s"
        )
        with conn.cursor() as cur:
            cur.execute(sql, (reference,))
            row = cur.fetchone()
        return row[0] if row else None

    def confirmed_trade_date(
        self, conn: Any, close_kind: str, now: datetime | None = None
    ) -> date | None:
        now = now or self._now_fn()
        candidate = self.latest_trading_day(conn, now.date())
        if candidate is None:
            return None
        close_at = CLOSE_TIMES.get(close_kind, dtime(15, 10))
        if candidate == now.date() and now.timetz().replace(tzinfo=None) < close_at:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT max(cal_date) FROM bp_trading_calendar"
                    " WHERE market='CN' AND is_trading AND cal_date < %s",
                    (candidate,),
                )
                row = cur.fetchone()
            return row[0] if row else None
        return candidate

    # -- state / lock -------------------------------------------------
    def dataset_last_success(self, conn: Any, dataset: str, adjust: str) -> date | None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_success_date FROM bp_etl_dataset_state"
                " WHERE dataset=%s AND adjust=%s",
                (dataset, adjust),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def _try_lock(self, conn: Any, dataset: str) -> bool:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (f"bp_etl:{dataset}",))
            row = cur.fetchone()
        return bool(row and row[0])

    def _unlock(self, conn: Any, dataset: str) -> None:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"bp_etl:{dataset}",))

    # -- wave ---------------------------------------------------------
    def run_wave(
        self,
        dataset: str,
        adjust: str,
        *,
        trade_date: date | None = None,
        wave: int = 1,
        now: datetime | None = None,
        force: bool = False,
    ) -> WaveResult:
        runner = self.runners.get(dataset)
        if runner is None:
            raise KeyError(f"dataset 未注册 runner: {dataset}")
        spec = runner.spec
        now = now or self._now_fn()
        result = WaveResult(dataset=dataset, adjust=adjust, trade_date=trade_date or now.date(), wave=wave)
        if not force and now.timetz().replace(tzinfo=None) < spec.schedule_start[adjust]:
            result.skipped = True
            result.skip_reason = "before_schedule"
            return result
        with self._conn_factory() as conn:
            if not self._try_lock(conn, dataset):
                result.skipped = True
                result.skip_reason = "locked"
                return result
            try:
                trade_date = trade_date or self.confirmed_trade_date(conn, spec.close_confirm, now)
                if trade_date is None:
                    result.skipped = True
                    result.skip_reason = "no_trade_date"
                    return result
                result.trade_date = trade_date
                last_success = self.dataset_last_success(conn, dataset, adjust)
                if last_success is not None and last_success >= trade_date and not force:
                    result.skipped = True
                    result.skip_reason = "already_done"
                    result.ok = True
                    return result
                codes = runner.universe(conn)
                rows = runner.fetch(adjust, codes, trade_date, self.channels)
                expected = len(codes)
                expected_fn = getattr(runner, "expected_count", None)
                if callable(expected_fn):
                    expected = int(expected_fn(conn, trade_date) or expected)
                return self._persist(conn, spec, result, codes, rows, now, expected)
            finally:
                self._unlock(conn, dataset)

    def _persist(
        self,
        conn: Any,
        spec: DatasetSpec,
        result: WaveResult,
        codes: Sequence[str],
        rows: Sequence[Any],
        now: datetime,
        expected_count: int | None = None,
    ) -> WaveResult:
        expected = expected_count if expected_count is not None else len(codes)
        trade_date = result.trade_date
        run = RunRecord(
            dataset=spec.name, trade_date=trade_date, wave=result.wave,
            status="running", target_coverage=spec.coverage_min,
        )
        run_id = start_run(conn, run)
        issues: list[QualityIssue] = []
        if spec.value_kind == "nav":
            written = write_navs(conn, rows) if self._write_enabled else 0
            got = {row.fund_code for row in rows if row.trade_date == trade_date}
            coverage = len(got) / expected if expected else 0.0
            report = QualityReport(ok=coverage >= spec.coverage_min, coverage=coverage)
        else:
            good, issues = sanitize_bars(spec.name, rows, today=now.date())
            written = write_bars(conn, spec, good) if self._write_enabled else 0
            touched = sorted({bar.symbol for bar in good})
            refresh_coverage(conn, spec, touched)
            report = evaluate(
                spec.name, trade_date, result.adjust, good, expected,
                coverage_min=spec.coverage_min,
            )
            issues.extend(report.issues)
        result.fetched = len(rows)
        result.written = written
        result.coverage = report.coverage
        result.ok = report.ok
        result.issues = issues

        got_symbols = (
            {row.fund_code for row in rows if row.trade_date == trade_date}
            if spec.value_kind == "nav"
            else {bar.symbol for bar in rows if bar.trade_date == trade_date}
        )
        missing = [code for code in codes if code not in got_symbols]

        run.status = "ok" if report.ok else "catching_up"
        run.achieved_coverage = report.coverage
        run.rows_written = written
        run.errors = len([issue for issue in issues if issue.severity == "error"])
        run.detail = {"adjust": result.adjust, "missing": len(missing), "issues": len(issues)}
        finish_run(conn, run_id, run)
        record_issues(conn, issues)
        self._record_source_health(conn, spec, trade_date, report.coverage)

        if report.ok:
            upsert_dataset_state(conn, spec.name, result.adjust, trade_date, run_id)
            clear_backlog(conn, spec.name, trade_date, result.adjust)
        else:
            result.next_retry_in = retry_interval(result.wave)
            upsert_backlog(
                conn,
                dataset=spec.name,
                trade_date=trade_date,
                adjust=result.adjust,
                symbols=missing,
                reason=f"coverage={report.coverage:.4f}<{spec.coverage_min}",
                next_retry_at=now + result.next_retry_in,
            )
        conn.commit()
        return result

    def _record_source_health(
        self, conn: Any, spec: DatasetSpec, trade_date: date, coverage: float
    ) -> None:
        snapshot = self.channels.snapshot()
        for source_name, data in snapshot.items():
            record_source_health(
                conn,
                stat_date=trade_date,
                dataset=spec.name,
                source=source_name,
                channel=str(data.get("channel") or "direct"),
                snapshot=data,
                coverage_today=coverage,
            )

    # -- batch / service ---------------------------------------------
    def run_due(self, *, now: datetime | None = None, force: bool = False) -> list[WaveResult]:
        now = now or self._now_fn()
        outcomes: list[WaveResult] = []
        with self._conn_factory() as conn:
            confirmed: dict[str, date | None] = {}
            for name, runner in self.runners.items():
                kind = runner.spec.close_confirm
                trade_date = confirmed.get(kind)
                if kind not in confirmed:
                    trade_date = self.confirmed_trade_date(conn, kind, now)
                    confirmed[kind] = trade_date
                if trade_date is None:
                    continue
                keys = ("nav",) if runner.spec.value_kind == "nav" else runner.spec.adjust_modes
                for adjust in keys:
                    last = self.dataset_last_success(conn, name, adjust)
                    if last is not None and last >= trade_date and not force:
                        continue
                    key = (name, adjust)
                    next_at = self._last_retry.get(key)
                    if next_at is not None and now < next_at and not force:
                        continue
                    outcome = self.run_wave(name, adjust, trade_date=trade_date, wave=1, now=now, force=force)
                    outcomes.append(outcome)
                    if not outcome.ok and not outcome.skipped:
                        self._last_retry[key] = now + (outcome.next_retry_in or RETRY_INITIAL)
                    else:
                        self._last_retry.pop(key, None)
        return outcomes

    def run_backlog(self, *, now: datetime | None = None) -> list[WaveResult]:
        """优先重试 backlog 中的未追平条目（跨交易日续跑）。"""
        now = now or self._now_fn()
        outcomes: list[WaveResult] = []
        with self._conn_factory() as conn:
            for name, runner in self.runners.items():
                kind = runner.spec.close_confirm
                trade_date = self.confirmed_trade_date(conn, kind, now)
                if trade_date is None:
                    continue
                keys = ("nav",) if runner.spec.value_kind == "nav" else runner.spec.adjust_modes
                for adjust in keys:
                    pending = due_backlog(conn, name, adjust, now, limit=5000)
                    if not pending:
                        continue
                    outcomes.append(
                        self.run_wave(name, adjust, trade_date=trade_date, wave=2, now=now, force=True)
                    )
        return outcomes

    def service(self) -> None:
        """常驻循环：始终追赶，不因未达标退出（无硬停）。"""
        logger.info("bp_etl service 启动：无限追赶模式")
        while True:
            try:
                self.run_due()
                self.run_backlog()
            except Exception:  # noqa: BLE001 - 单轮失败不得终止常驻进程
                logger.exception("ETL 轮次异常（继续下一轮）")
            self._sleep(POLL_SECONDS)