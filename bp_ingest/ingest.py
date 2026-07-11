"""增量更新引擎。

对每个有效配置:
  1. 计算增量窗口(新品种从 start_date/默认 2017; 已有数据则回看 REVISION_DAYS)
  2. 交易日护栏(已到期望最新交易日则跳过)
  3. 适配器抓取(带重试) + 归一化
  4. 计算 pct_change(接口已提供则直接用, 否则按上一交易日 close 本地计算)
  5. 幂等 upsert
  6. 新品种首拉成功回写真实最早日期; 记录 last_sync_at / last_error
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_random_exponential

from . import db
from .calendar import TradingCalendar
from .config import AppConfig
from .db import ConfigRow, QuoteRow
from .sources import get_adapter, fetch_with_fallback

logger = logging.getLogger(__name__)


def _polite_sleep(app: AppConfig) -> None:
    """标的抓取之间的随机抖动等待, 降低被限流概率。

    默认 2.5-6.0s(BP_REQUEST_INTERVAL=2.5 + BP_REQUEST_JITTER=3.5);
    服务器"慢落库"可调大, 如 interval=5/jitter=10 → 5-15s。
    """
    time.sleep(app.request_interval + random.uniform(0, app.request_jitter))


@dataclass
class SyncResult:
    symbol: str
    source: str
    status: str  # ok / skip / error
    rows: int = 0
    detail: str = ""


def _to_decimal(value) -> Optional[Decimal]:
    if value is None or pd.isna(value):
        return None
    return Decimal(str(value))


def _to_int(value) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    try:
        return int(round(float(value)))
    except (ValueError, TypeError):
        return None


def _compute_pct_change(
    df: pd.DataFrame, prev_close: Optional[Decimal], provides_pct: bool
) -> pd.DataFrame:
    """补全 pct_change 列(单位 %)。接口已提供则保留; 否则按 close 序列计算。"""
    df = df.copy()
    if provides_pct and df["pct_change"].notna().any():
        return df

    closes = df["close"].tolist()
    pcts: list[Optional[float]] = []
    base = float(prev_close) if prev_close is not None else None
    for c in closes:
        if base is not None and base != 0:
            pcts.append((float(c) / base - 1.0) * 100.0)
        else:
            pcts.append(None)
        base = float(c)
    df["pct_change"] = pcts
    return df


def _build_rows(df: pd.DataFrame, cfg: ConfigRow) -> list[QuoteRow]:
    rows: list[QuoteRow] = []
    for r in df.itertuples(index=False):
        rows.append(
            QuoteRow(
                trade_date=r.trade_date,
                symbol=cfg.symbol,
                source=cfg.source,
                category=cfg.category,
                name=cfg.name,
                open=_to_decimal(r.open),
                high=_to_decimal(r.high),
                low=_to_decimal(r.low),
                close=_to_decimal(r.close),
                volume=_to_int(r.volume),
                amount=_to_decimal(r.amount),
                turnover_rate=_to_decimal(r.turnover_rate),
                pct_change=_to_decimal(r.pct_change),
            )
        )
    return rows


def _sync_one(
    conn,
    cfg: ConfigRow,
    cal: TradingCalendar,
    app: AppConfig,
    today: date,
) -> SyncResult:
    adapter = get_adapter(cfg.source)

    last_date = db.get_last_trade_date(conn, cfg.symbol, cfg.source)
    expected_latest = cal.expected_latest(today, app.lag_days)

    # 交易日护栏: 已到最新则跳过
    if last_date is not None and expected_latest is not None and last_date >= expected_latest:
        return SyncResult(cfg.symbol, cfg.source, "skip", 0, f"已最新 @ {last_date}")

    # 增量窗口
    if last_date is None:
        start = cfg.start_date or app.default_start_date
    else:
        start = last_date - timedelta(days=app.revision_days)
    end = expected_latest or today

    if start > end:
        return SyncResult(cfg.symbol, cfg.source, "skip", 0, "窗口为空")

    # 函数内重试(带随机指数退避+抖动), 抗东财偶发断连/限流; 次数与退避上限由 config 控制
    @retry(
        stop=stop_after_attempt(app.max_retries),
        wait=wait_random_exponential(multiplier=1, max=60),
        reraise=True,
    )
    def _fetch() -> pd.DataFrame:
        return fetch_with_fallback(cfg.source, cfg.symbol, start, end, cfg.extra_params)

    df = _fetch()
    if df.empty:
        # 新品种首拉无数据也记成功(避免反复重试), 不回写 start_date
        db.mark_sync_success(conn, cfg.config_id)
        return SyncResult(cfg.symbol, cfg.source, "ok", 0, "无新增数据")

    prev_close = db.get_prev_close(conn, cfg.symbol, cfg.source, df["trade_date"].min())
    df = _compute_pct_change(df, prev_close, adapter.provides_pct)

    rows = _build_rows(df, cfg)
    n = db.upsert_quotes(conn, rows)

    # 新品种(原 start_date 为空)首拉成功 -> 回写真实最早日期
    writeback = df["trade_date"].min() if cfg.start_date is None else None
    db.mark_sync_success(conn, cfg.config_id, writeback)

    return SyncResult(
        cfg.symbol, cfg.source, "ok", n,
        f"{df['trade_date'].min()} ~ {df['trade_date'].max()}",
    )


def run(
    app: AppConfig,
    symbols: Optional[list[str]] = None,
    refresh_clean: bool = True,
) -> list[SyncResult]:
    """执行一轮增量更新, 返回每个标的的结果。

    refresh_clean=True 时, 增量入库后重建受影响标的的 bp_quote_clean。
    """
    today = date.today()
    cal = TradingCalendar()
    cal.load()

    results: list[SyncResult] = []
    with db.connect(app.db) as conn:
        conn.autocommit = False
        configs = db.fetch_active_configs(conn, symbols)
        logger.info("待处理配置: %d 个", len(configs))

        def _process(cfg: ConfigRow, *, mark_error: bool) -> SyncResult:
            """抓取单个配置; mark_error=False 时首轮失败不落库(留待第二遍重扫)。"""
            label = f"{cfg.symbol}@{cfg.source}"
            try:
                res = _sync_one(conn, cfg, cal, app, today)
                conn.commit()
                logger.info("[%s] %s rows=%d %s", res.status.upper(), label, res.rows, res.detail)
                return res
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                msg = f"{type(exc).__name__}: {exc}"
                if mark_error:
                    try:
                        db.mark_sync_error(conn, cfg.config_id, msg)
                        conn.commit()
                    except Exception:  # noqa: BLE001
                        conn.rollback()
                    logger.error("[ERROR] %s -> %s", label, msg)
                else:
                    logger.warning("[RETRY-PENDING] %s -> %s", label, msg)
                return SyncResult(cfg.symbol, cfg.source, "error", 0, msg)

        # 首轮: 失败先不落库, 收集待重扫
        failed_idx: list[int] = []
        for i, cfg in enumerate(configs):
            res = _process(cfg, mark_error=False)
            results.append(res)
            if res.status == "error":
                failed_idx.append(i)
            _polite_sleep(app)

        # 第二遍: 对首轮失败标的静默后重扫; 仍失败才最终记 error, 等下一轮调度。
        # 等待 30-60s(EM 封禁窗约 5min, 等够久再重扫比快速重试更易恢复)
        if failed_idx:
            wait = random.uniform(30, 60)
            logger.info("首轮 %d 个失败, 静默 %.1fs 后重扫", len(failed_idx), wait)
            time.sleep(wait)
            for i in failed_idx:
                results[i] = _process(configs[i], mark_error=True)
                _polite_sleep(app)

        if refresh_clean:
            updated = [
                r.symbol for r in results if r.status in ("ok",) and r.rows > 0
            ]
            # 清洗恢复: 即使本次无新数据(rows=0), 也要追赶"清洗表落后于原始表"的标的。
            # 否则一旦某次 rebuild_clean 失败, 后续因 rows=0 不再重洗, 清洗表永久滞后,
            # 组合 readiness 检查永远 false, T-1 自动更新卡死。
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT DISTINCT a.symbol
                           FROM bp_index_config a
                           JOIN bp_asset_data_status s
                             ON s.symbol = a.symbol AND s.source = a.source
                           WHERE a.is_deleted = 0
                             AND a.is_selectable = TRUE
                             AND (s.last_clean_date IS NULL
                                  OR s.last_clean_date < s.last_raw_date)"""
                    )
                    stale = [row[0] for row in cur.fetchall()]
            except Exception:  # noqa: BLE001
                stale = []
            clean_targets = list({*updated, *stale})
            if clean_targets:
                try:
                    from bp_api.quant.cleaning import rebuild_clean

                    logger.info(
                        "刷新清洗表 bp_quote_clean: 新数据 %d + 落后追赶 %d = %d 个标的",
                        len(set(updated)), len(set(stale) - set(updated)), len(set(clean_targets)),
                    )
                    rebuild_clean(conn, symbols=clean_targets, cal=cal)
                except Exception as exc:  # noqa: BLE001
                    logger.error("清洗表刷新失败: %s", exc)
                else:
                    # 挂钩 CFFEX 的四指数更新后, 失效看板快照 (现货追上期货日)
                    cffex_idx = {"000300", "000016", "000905", "000852"}
                    if cffex_idx.intersection(clean_targets):
                        try:
                            from bp_api.cffex import invalidate_cffex_spot_cache
                            invalidate_cffex_spot_cache()
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("失效 CFFEX 看板缓存失败: %s", exc)

        if refresh_clean:
            try:
                from bp_api.daily_update import enqueue_ready_portfolios, refresh_all_asset_status

                refresh_all_asset_status(conn)
                queued = enqueue_ready_portfolios(conn)
                conn.commit()
                if queued:
                    logger.info("行情完成后已排队更新 %d 个 portfolio", len(queued))
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                logger.error("自动更新 portfolio 排队失败: %s", exc)

    _log_summary(results)
    return results


def _log_summary(results: list[SyncResult]) -> None:
    ok = sum(1 for r in results if r.status == "ok")
    skip = sum(1 for r in results if r.status == "skip")
    err = sum(1 for r in results if r.status == "error")
    total_rows = sum(r.rows for r in results)
    logger.info(
        "本轮完成 @ %s | 成功=%d 跳过=%d 失败=%d 写入行数=%d",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ok, skip, err, total_rows,
    )
    if err:
        for r in results:
            if r.status == "error":
                logger.warning("失败标的: %s@%s -> %s", r.symbol, r.source, r.detail)
