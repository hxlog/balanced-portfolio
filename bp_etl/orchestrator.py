"""数据集波次编排：收盘确认 → 抓取 → 写库 → 质量门 → 覆盖 → 未达标 backfill。

核心语义（设计与 Q 指示）：
- **无硬停**：单波未达标不终止；按 10→30 分钟退避无限重试（跨交易日由 backlog 续跑），
  直到 `bp_etl_dataset_state.last_success_date` 追平最新确认交易日；
- 目标时点只用于升级告警（管理页红黄绿），不用于停止；
- 幂等：同 dataset 用 Postgres advisory lock 防重入；重复波次 UPSERT 安全；
- 收盘确认：A 15:10 / HK 16:15 / FUND 20:00（CST），未确认不写当日；
- **backlog 默认无限重试**：跨交易日的历史缺口默认永不过期（长假/源故障 >5 天
  造成的缺口必须最终补齐）。只有显式设置 `BP_ETL_BACKLOG_MAX_AGE_DAYS=<正整数>`
  才会丢弃超期历史日期，且丢弃时写 `bp_etl_quality_issue` 告警（管理端
  data-health issues 可见），绝不静默丢数；`0`/未设置/非法值均视为关闭。
"""

from __future__ import annotations

import logging
import os
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
    due_backlog_dates,
    finish_run,
    prune_backlog_symbols,
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
# 旧链清洗刷新节流（避免每次 catching_up 重试都跑 747 标的清洗）
LEGACY_CLEAN_MIN_INTERVAL = timedelta(hours=4)


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
        if runners is None:
            from bp_etl.datasets import get_runners  # noqa: PLC0415

            runners = get_runners(config)
        self.runners: dict[str, DatasetRunner] = dict(runners)
        self.channels = channel_manager or ChannelManager(config)
        self._conn_factory = conn_factory or default_conn_factory(config)
        self._now_fn = now_fn or _now_cn
        self._sleep = sleep_fn
        self._write_enabled = config.write_enabled if write_enabled is None else write_enabled
        self._last_retry: dict[tuple[str, str], datetime] = {}
        self._legacy_clean_last: datetime | None = None
        # backlog 历史日期保留上限（自然日）：**默认关闭 = 永不丢弃**（None）。
        # 长假/源故障导致缺口 >5 天时，静默丢弃会留下永久空洞，必须保持跨日无限
        # 重试语义。仅当显式设置 BP_ETL_BACKLOG_MAX_AGE_DAYS>0 才丢弃超期日期，
        # 且丢弃时写 bp_etl_quality_issue 告警（见 _record_backlog_expired）。
        raw_age = (os.getenv("BP_ETL_BACKLOG_MAX_AGE_DAYS") or "").strip()
        self._backlog_max_age_days: int | None = None
        if raw_age:
            try:
                parsed = int(raw_age)
            except ValueError:
                logger.warning(
                    "BP_ETL_BACKLOG_MAX_AGE_DAYS=%r 非法（需正整数），保持默认关闭（不丢弃历史缺口）",
                    raw_age,
                )
            else:
                # 0 / 负数 = 明确关闭；正整数 = 显式开启超期丢弃
                self._backlog_max_age_days = parsed if parsed > 0 else None

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
                # 验证模式（源大面积降级时）：不再抓取，直接按库内当日覆盖判定是否追平；
                # 用于已由回退/因子路径补齐后，让 state 正常推进（否则会永远卡在"未追平"）。
                if (os.getenv("BP_ETL_VERIFY_ONLY") or "off").strip().lower() in ("1", "on", "true", "yes"):
                    rows = []
                else:
                    rows = runner.fetch(adjust, codes, trade_date, self.channels)
                expected = len(codes)
                expected_fn = getattr(runner, "expected_count", None)
                if callable(expected_fn):
                    try:
                        expected = int(expected_fn(conn, trade_date, adjust) or expected)
                    except TypeError:
                        expected = int(expected_fn(conn, trade_date) or expected)
                return self._persist(conn, spec, result, codes, rows, now, expected)
            finally:
                self._unlock(conn, dataset)

    def _db_coverage(
        self,
        conn: Any,
        spec: DatasetSpec,
        trade_date: date,
        adjust: str,
        expected: int,
        codes: Sequence[str] | None = None,
    ) -> float:
        """覆盖率以**库内当日已落库行数**为口径（增量波次只写少量缺口，不能按本波 bars 计算）。

        codes 非空时只统计**当前 universe** 内的标的（backlog 对账口径）：
        旧 universe 遗留在表里的其它 symbol 不得把覆盖率抬高，避免把真正缺的
        当前标的误判为已补齐。
        """
        if not expected:
            return 0.0
        keys = list(dict.fromkeys(codes)) if codes is not None else None
        if keys is not None and not keys:
            return 0.0
        with conn.cursor() as cur:
            if spec.value_kind == "nav":
                if keys is None:
                    cur.execute(
                        "SELECT count(DISTINCT fund_code) FROM bp_fund_nav_daily WHERE trade_date = %s",
                        (trade_date,),
                    )
                else:
                    cur.execute(
                        "SELECT count(DISTINCT fund_code) FROM bp_fund_nav_daily"
                        " WHERE trade_date = %s AND fund_code = ANY(%s)",
                        (trade_date, keys),
                    )
            else:
                if keys is None:
                    cur.execute(
                        f"SELECT count(DISTINCT {spec.key_column}) FROM {spec.table}"
                        " WHERE trade_date = %s AND adjust = %s",
                        (trade_date, adjust),
                    )
                else:
                    cur.execute(
                        f"SELECT count(DISTINCT {spec.key_column}) FROM {spec.table}"
                        " WHERE trade_date = %s AND adjust = %s"
                        f" AND {spec.key_column} = ANY(%s)",
                        (trade_date, adjust, keys),
                    )
            row = cur.fetchone()
        achieved = int(row[0]) if row and row[0] is not None else 0
        return min(1.0, achieved / expected)

    def _db_present_symbols(
        self, conn: Any, spec: DatasetSpec, trade_date: date, adjust: str
    ) -> set[str]:
        with conn.cursor() as cur:
            if spec.value_kind == "nav":
                cur.execute(
                    "SELECT DISTINCT fund_code FROM bp_fund_nav_daily WHERE trade_date = %s",
                    (trade_date,),
                )
            else:
                cur.execute(
                    f"SELECT DISTINCT {spec.key_column} FROM {spec.table}"
                    " WHERE trade_date = %s AND adjust = %s",
                    (trade_date, adjust),
                )
            return {row[0] for row in cur.fetchall()}

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
            coverage = (
                self._db_coverage(
                    conn, spec, trade_date, result.adjust, expected, codes=codes
                )
                if self._write_enabled
                else 0.0
            )
            report = QualityReport(ok=coverage >= spec.coverage_min, coverage=coverage)
        else:
            good, issues = sanitize_bars(spec.name, rows, today=now.date())
            written = write_bars(conn, spec, good) if self._write_enabled else 0
            if self._write_enabled:
                refresh_coverage(conn, spec, sorted({bar.symbol for bar in good}))
            report = evaluate(
                spec.name, trade_date, result.adjust, good, expected,
                coverage_min=spec.coverage_min,
            )
            if self._write_enabled:
                # 增量波次按库内当日覆盖重算（本波只补缺口，不能拿本波行数当覆盖率）；
                # evaluate 的 coverage issue 反映的是本波取数比例，不是库内实况，剔除。
                wave_issues = [issue for issue in report.issues if issue.kind != "coverage"]
                coverage = self._db_coverage(
                    conn, spec, trade_date, result.adjust, expected, codes=codes
                )
                # 追平判定只看库内覆盖率：被质量门拒绝的行已不入库、且 issue 已落库审计，
                # 不应因个别源脏行把整个 dataset 永远卡在未追平。
                report = QualityReport(
                    ok=coverage >= spec.coverage_min,
                    coverage=coverage,
                    issues=wave_issues,
                )
            issues.extend(report.issues)
        result.fetched = len(rows)
        result.written = written
        result.coverage = report.coverage
        result.ok = report.ok
        result.issues = issues

        if self._write_enabled:
            present = self._db_present_symbols(conn, spec, trade_date, result.adjust)
            if spec.value_kind == "nav":
                got_symbols = {row.fund_code for row in rows if row.trade_date == trade_date}
                missing = [code for code in codes if code not in got_symbols]
            else:
                missing = [code for code in codes if code not in present]
        else:
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
            if self._write_enabled:
                upsert_dataset_state(conn, spec.name, result.adjust, trade_date, run_id)
                clear_backlog(conn, spec.name, trade_date, result.adjust)
        else:
            result.next_retry_in = retry_interval(result.wave)
            if self._write_enabled:
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
        self._maybe_refresh_legacy_clean(conn, spec, now, result, report)
        self._record_dataset_freshness(conn, spec, trade_date, result, report)
        return result

    def _maybe_refresh_legacy_clean(
        self,
        conn: Any,
        spec: DatasetSpec,
        now: datetime,
        result: WaveResult,
        report: QualityReport,
    ) -> None:
        """旧链清洗/资产状态刷新（P2 收尾）。

        触发条件：legacy_index hfq 波次（第二口径，bfq 已先写）且已过收盘窗口，
        本轮确有抓取或已追平；节流 4h。**不依赖 coverage 达标**——旧链含少量
        不可达自定义指数时覆盖率可能永远 <0.90，但可达资产的清洗必须照常刷新，
        否则组合 T-1 自动更新会被旧 clean 数据卡死。
        """
        if not self._write_enabled or spec.name != "legacy_index":
            return
        if result.adjust != "hfq":
            return
        if now.timetz().replace(tzinfo=None) < dtime(16, 30):
            return
        last = self._legacy_clean_last
        if last is not None and now - last < LEGACY_CLEAN_MIN_INTERVAL:
            return
        if not (report.ok or result.fetched > 0 or result.written > 0):
            return
        try:
            from bp_etl.cleaning_hook import refresh_legacy_clean

            refresh_legacy_clean(conn)
            self._legacy_clean_last = now
        except Exception:  # noqa: BLE001
            logger.warning("旧链清洗刷新失败（下一轮再试）", exc_info=True)

    def _record_dataset_freshness(
        self,
        conn: Any,
        spec: DatasetSpec,
        trade_date: date,
        result: WaveResult,
        report: QualityReport,
    ) -> None:
        """数据集收尾同步全局新鲜度（P0-6）。

        只记录新链 4 类（旧链 index_quotes 由 scripts/index_quotes_free.py 负责）；
        未追平波次写 status=lagging（as_of 仍取本轮目标日），追平写 ok。
        失败只告警：新鲜度是增强信号，不得影响 ETL 波次结果。
        """
        if not self._write_enabled:
            return
        mapping = {"a_stock": "a_stock", "hk_stock": "hk_stock", "etf": "etf", "fund_nav": "fund_nav"}
        key = mapping.get(spec.name)
        if key is None:
            return
        try:
            from bp_api.freshness import record_freshness  # noqa: PLC0415 - 惰性导入

            record_freshness(
                conn,
                key,
                trade_date,
                status="ok" if report.ok else "lagging",
                source="bp_etl",
                meta={
                    "dataset": spec.name,
                    "adjust": result.adjust,
                    "coverage": round(float(report.coverage or 0.0), 6),
                    "written": int(result.written or 0),
                    "wave": result.wave,
                },
            )
        except Exception:  # noqa: BLE001
            logger.warning("写入数据新鲜度失败 dataset=%s", spec.name, exc_info=True)

    def _record_backlog_expired(
        self,
        conn: Any,
        dataset: str,
        adjust: str,
        trade_date: date,
        age_days: int,
        dropped: int,
    ) -> None:
        """显式开启超期丢弃时写质量/健康告警（绝不静默丢数）。

        - `bp_etl_quality_issue` 落一行 kind=backlog_expired/severity=error，
          管理端 /api/admin/data-health/issues 可见；
        - 同时 warning 日志（进程日志告警）。
        写告警失败只记日志，不阻断 backlog 清理（清理本身由调用方提交）。
        """
        logger.warning(
            "backlog 历史日期超期放弃 %s/%s %s (age=%dd, max=%dd, dropped=%d) —— "
            "已写 bp_etl_quality_issue 告警",
            dataset, adjust, trade_date, age_days,
            self._backlog_max_age_days or 0, dropped,
        )
        try:
            record_issues(
                conn,
                [
                    QualityIssue(
                        dataset=dataset,
                        kind="backlog_expired",
                        severity="error",
                        trade_date=trade_date,
                        detail={
                            "adjust": adjust,
                            "age_days": age_days,
                            "max_age_days": self._backlog_max_age_days,
                            "dropped_rows": dropped,
                            "reason": "BP_ETL_BACKLOG_MAX_AGE_DAYS 显式开启，超期日期不再重放",
                        },
                    )
                ],
            )
        except Exception:  # noqa: BLE001 - 告警失败不得阻断 backlog 清理
            logger.warning(
                "写入 backlog 超期告警失败 dataset=%s/%s %s",
                dataset, adjust, trade_date, exc_info=True,
            )

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
    @staticmethod
    def _skipped_datasets() -> set[str]:
        raw = os.getenv("BP_ETL_SKIP_DATASETS") or ""
        return {item.strip() for item in raw.split(",") if item.strip()}

    def run_due(self, *, now: datetime | None = None, force: bool = False) -> list[WaveResult]:
        """执行所有已到期且未追平的波次：按 target_time 升序（越逾期越先跑，保障 SLA）。"""
        from datetime import time as _time

        now = now or self._now_fn()
        outcomes: list[WaveResult] = []
        with self._conn_factory() as conn:
            confirmed: dict[str, date | None] = {}
            candidates: list[tuple[_time, str, str, date]] = []
            skipped = self._skipped_datasets()
            for name, runner in self.runners.items():
                if name in skipped:
                    continue
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
                    target = runner.spec.target_time.get(adjust) or _time(23, 59)
                    candidates.append((target, name, adjust, trade_date))
            candidates.sort(key=lambda item: (item[0], item[1]))
            for _target, name, adjust, trade_date in candidates:
                outcome = self.run_wave(
                    name, adjust, trade_date=trade_date, wave=1, now=now, force=force
                )
                outcomes.append(outcome)
                key = (name, adjust)
                if not outcome.ok and not outcome.skipped:
                    self._last_retry[key] = now + (outcome.next_retry_in or RETRY_INITIAL)
                else:
                    self._last_retry.pop(key, None)
        return outcomes

    def run_backlog(
        self, *, now: datetime | None = None, limit: int | None = None
    ) -> list[WaveResult]:
        """优先重试 backlog 中的未追平条目（跨交易日续跑）。

        limit：本轮最多补几个 (dataset, adjust) 波次（常驻循环用 1，避免单波长尾
        拖住下一轮 run_due，保障收盘当日波次 SLA）。
        """
        now = now or self._now_fn()
        outcomes: list[WaveResult] = []
        with self._conn_factory() as conn:
            skipped = self._skipped_datasets()
            for name, runner in self.runners.items():
                if name in skipped:
                    continue
                if limit is not None and len(outcomes) >= limit:
                    break
                keys = ("nav",) if runner.spec.value_kind == "nav" else runner.spec.adjust_modes
                for adjust in keys:
                    if limit is not None and len(outcomes) >= limit:
                        break
                    # --- 对账 1/3：以「当前 universe」收敛旧 universe 的 backlog symbol 行 ---
                    # 旧链 universe 口径收敛（9,600 -> 可交易子集）后，旧 universe 的
                    # symbol 行永远不会被重放（9,434/9,496 条空转的根因），每轮先按
                    # 当前 universe 删除这些行；universe 为空（异常态）时不动 backlog。
                    try:
                        codes = runner.universe(conn)
                    except Exception:  # noqa: BLE001 - universe 异常不影响其它 dataset
                        logger.warning("backlog 对账取 universe 失败 dataset=%s", name, exc_info=True)
                        codes = []
                    expected = len(codes)
                    if codes:
                        try:
                            pruned = prune_backlog_symbols(conn, name, adjust, codes)
                        except Exception:  # noqa: BLE001
                            logger.warning("backlog 旧 universe 清理失败 dataset=%s", name, exc_info=True)
                            pruned = 0
                        if pruned:
                            conn.commit()
                            logger.info(
                                "backlog 旧 universe 条目收敛 %s/%s: 删除 %d 条（当前 universe=%d）",
                                name, adjust, pruned, len(codes),
                            )
                    # --- 对账 2/3：逐 backlog trade_date 按当前 universe 覆盖率判定 ---
                    # 关键：以 backlog 自身 trade_date 重放（此前误用"当前确认日"，
                    # 导致历史缺口条目永不清理、每小时重复空跑）。
                    backlog_dates = due_backlog_dates(conn, name, adjust, now, limit=5)
                    for trade_date in backlog_dates:
                        if limit is not None and len(outcomes) >= limit:
                            break
                        # 先按库内覆盖对账：历史缺口可能已被回退/因子路径补齐，
                        # 无需再发慢请求，直接清 backlog（避免每小时重复空跑）。
                        try:
                            coverage = self._db_coverage(
                                conn, runner.spec, trade_date, adjust, expected,
                                codes=codes or None,
                            )
                        except Exception:  # noqa: BLE001
                            coverage = 0.0
                        if coverage >= runner.spec.coverage_min:
                            cleared = clear_backlog(conn, name, trade_date, adjust)
                            conn.commit()
                            logger.info(
                                "backlog 对账已达标，清理 %s/%s %s (%d 条, coverage=%.4f)",
                                name, adjust, trade_date, cleared, coverage,
                            )
                            continue
                        # --- 对账 3/3：**仅显式开启**时才放弃超期历史日期 ---
                        # 默认（None）不丢弃：长假/源故障 >5 天的真实缺口会继续跨日
                        # 无限重试，直到补齐，绝不静默留下永久空洞。显式开启时丢弃
                        # 必须落 bp_etl_quality_issue/health 告警，可审计。
                        age_days = (now.date() - trade_date).days
                        if (
                            self._backlog_max_age_days is not None
                            and age_days > self._backlog_max_age_days
                        ):
                            dropped = clear_backlog(conn, name, trade_date, adjust)
                            self._record_backlog_expired(
                                conn, name, adjust, trade_date, age_days, dropped
                            )
                            conn.commit()
                            continue
                        outcomes.append(
                            self.run_wave(
                                name, adjust, trade_date=trade_date,
                                wave=2, now=now, force=True,
                            )
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