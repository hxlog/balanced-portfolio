"""数据访问层: 资产清单、价格面板、组合 CRUD、回测编排与结果读写。"""

from __future__ import annotations

import logging
import math
import multiprocessing as mp
import os
import platform
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
import psycopg
from psycopg.types.json import Json

from .quant.attribution import compute_attribution
from .quant.backtest import BacktestResult, run_backtest
from .quant.metrics import compute_metrics
from .quant.optimizer import build_quadrant_assets
from .schemas import CreatePortfolioIn, UpdatePortfolioIn
from .settings import ApiSettings
from . import cache, tasking

logger = logging.getLogger(__name__)

STALE_TOLERANCE_DAYS = 10  # 某资产相对最新滞后超过该交易日数 → 视为停更并报错


def _json_safe(obj):
    """递归把 NaN/Inf 转 None, 防止 PG JSON 拒绝(NaN/Infinity 非合法 JSON token)。
    应用于所有 Json() 实参, 兜底指标级 NaN(如零波动率时 sharpe)。"""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if obj is None or isinstance(obj, (int, bool, str)):
        return obj
    # numpy 标量等可转 float 的类型
    try:
        f = float(obj)
    except (TypeError, ValueError):
        return obj
    return None if (math.isnan(f) or math.isinf(f)) else f


def _in_daemon_process() -> bool:
    """当前是否运行在守护进程内(如 Celery prefork worker)。

    守护进程禁止再 fork 子进程, 此时不能使用 ProcessPoolExecutor,
    否则会抛 "daemonic processes are not allowed to have children"。
    """
    try:
        return bool(mp.current_process().daemon)
    except Exception:  # noqa: BLE001
        return False

# 预计算的全部优化方法
BACKTEST_METHODS = [
    "quadrant_inner_sharpe_outer_rp",
    "all_risk_parity",
    "all_max_sharpe",
    "sharpe_sq_risk_budget",
]

# 与前端 web/lib/api.ts METHOD_LABELS 对齐, 供进度展示。
METHOD_LABELS_CN = {
    "quadrant_inner_sharpe_outer_rp": "象限内最大化·象限间风险平价",
    "all_risk_parity": "全体风险平价",
    "all_max_sharpe": "全体最大化夏普",
    "sharpe_sq_risk_budget": "按优化指标的平方分配风险",
}

# 回测 6 步: 1=加载行情/参数, 2-5=四种方法, 6=写入结果。
TASK_TOTAL_STEPS = 4 * 100 + 2


def _step_label(method: str, idx: int) -> str:
    """idx 为方法在 BACKTEST_METHODS 中的 0-based 下标, 步骤号=idx+2。"""
    return f"步骤 {idx + 2}/6：回测 {METHOD_LABELS_CN.get(method, method)}"


def _compute_method_job(args) -> tuple[str, tuple[BacktestResult, dict], float]:
    (
        method,
        prices,
        bench,
        quadrant_assets,
        ratio,
        lookback_days,
        min_window,
        max_weight,
        rebalance_band,
        risk_free_rate,
        fee_rate,
        slippage_rate,
        stamp_duty_rate,
        trading_days,
        start_date,
    ) = args
    t0 = time.perf_counter()
    result = run_backtest(
        prices=prices,
        benchmark=bench,
        quadrant_assets=quadrant_assets,
        method=method,
        ratio=ratio,
        lookback=lookback_days,
        min_window=min_window,
        max_weight=max_weight,
        rebalance_band=rebalance_band,
        risk_free=risk_free_rate,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        stamp_duty_rate=stamp_duty_rate,
        trading_days=trading_days,
        user_start=start_date,
    )
    nav_series = result.nav["nav"]
    bench_series = result.nav["benchmark_nav"]
    metrics = {
        "portfolio": compute_metrics(nav_series, bench_series, risk_free_rate, trading_days),
        "benchmark": compute_metrics(bench_series, None, risk_free_rate, trading_days),
    }
    return method, (result, metrics), time.perf_counter() - t0

# 候选基准注册表: legs = [(权重, symbol, source), ...]; 多腿为按日再平衡的组合基准
BENCHMARKS: dict[str, dict] = {
    "000300": {"name": "沪深300", "legs": [(1.0, "000300", "cn_index_em")]},
    "000510": {"name": "中证A500", "legs": [(1.0, "000510", "cn_index_em")]},
    "000905": {"name": "中证500", "legs": [(1.0, "000905", "cn_index_em")]},
    "HSI": {"name": "恒生指数", "legs": [(1.0, "HSI", "hk_index_em")]},
    "bond6040": {
        "name": "60/40经典股债",
        "legs": [(0.6, "10Y", "bond_csi_treasury"), (0.4, "000300", "cn_index_em")],
    },
}
INFO_RATIO_BENCH = "000300"  # 信息比率固定基准: 沪深300
DEFAULT_BENCHMARK_KEY = "bond6040"


def asset_key(symbol: str, source: str) -> str:
    return f"{symbol}@{source}"


def _unique_asset_pairs(assets: list[dict]) -> list[tuple[str, str]]:
    """去重后的 (symbol, source) 列表, 保持首次出现顺序。"""
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    for a in assets:
        t = (a["symbol"], a["source"])
        if t not in seen:
            seen.add(t)
            pairs.append(t)
    return pairs


def _asset_quadrants(assets: list[dict]) -> dict[str, list[str]]:
    """资产 key → 所属象限列表(可多个)。"""
    out: dict[str, list[str]] = {}
    for a in assets:
        k = asset_key(a["symbol"], a["source"])
        q = a["quadrant"]
        if q not in out.get(k, []):
            out.setdefault(k, []).append(q)
    return out


# ---------------------------------------------------------------------
# 资产清单
# ---------------------------------------------------------------------
def list_assets(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.symbol, c.source, c.category, c.name, s.asset_class,
                   s.vendor, c.extra_params->>'adjust' AS adjust
            FROM bp_index_config c
            JOIN bp_data_source s ON s.code = c.source
            WHERE c.is_deleted = 0 AND c.is_selectable = TRUE
            ORDER BY s.asset_class, c.symbol
            """
        )
        return [
            {
                "symbol": r[0], "source": r[1], "category": r[2], "name": r[3],
                "asset_class": r[4], "vendor": r[5], "adjust": r[6],
            }
            for r in cur.fetchall()
        ]


# ---------------------------------------------------------------------
# 价格面板
# ---------------------------------------------------------------------
def _load_series(conn: psycopg.Connection, symbol: str, source: str) -> pd.Series:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, close FROM bp_quote_clean "
            "WHERE symbol = %s AND source = %s ORDER BY trade_date",
            (symbol, source),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.Series(dtype="float64")
    idx = [r[0] for r in rows]
    vals = [float(r[1]) for r in rows]
    return pd.Series(vals, index=idx, name=asset_key(symbol, source))


def load_price_panel(
    conn: psycopg.Connection, pairs: list[tuple[str, str]]
) -> pd.DataFrame:
    """构建宽表价格面板(列=symbol@source), 截断到"全体成分最近完整日"。

    取各成分 last_valid_index 的最小值作为面板末端 → 不存在尾部缺口,
    nav 物理上止于"所有成分都有数据的那一天"。某成分滞后则整组回退到该成分的最近完整日
    (T-N 回退); 不再用脏数据(fillna 0)延伸, 也不因滞后直接 raise。
    """
    series = {}
    for symbol, source in pairs:
        s = _load_series(conn, symbol, source)
        if s.empty:
            raise ValueError(f"{asset_key(symbol, source)} 无清洗行情数据, 请先运行 ingest/clean")
        series[asset_key(symbol, source)] = s

    panel = pd.DataFrame(series).sort_index()
    last_valids = {k: panel[k].last_valid_index() for k in panel.columns}
    end = min(last_valids.values())
    panel = panel.loc[:end]  # 截断尾部缺口: nav 止于全体最近完整日

    # 停更告警(仅日志, 不 raise: 截断已消除 NaN, 组合按 min 完整日回退是预期行为)
    freshest = max(last_valids.values())
    for k, lv in last_valids.items():
        gap_days = (freshest - lv).days if freshest and lv else 0
        if gap_days > STALE_TOLERANCE_DAYS * 2:
            logger.warning("资产 %s 疑似停更(最后 %s, 最新 %s, 差 %d 天)", k, lv, freshest, gap_days)
    return panel


# ---------------------------------------------------------------------
# 组合定义
# ---------------------------------------------------------------------
@dataclass
class PortfolioDef:
    portfolio_id: int
    name: str
    description: str
    method: str
    ratio: str
    lookback_days: int
    start_date: date
    benchmark_key: str
    max_weight: Optional[float]
    rebalance_band: float
    is_demo: bool
    owner_user_id: Optional[int]
    risk_free_rate: float
    fee_rate: float
    slippage_rate: float
    stamp_duty_rate: float
    result_version: int
    data_as_of_date: Optional[date]
    assets: list[dict]  # {symbol, source, quadrant, display_name}


def _read_def(conn: psycopg.Connection, pid: int) -> PortfolioDef:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT portfolio_id, name, description, method, ratio, lookback_days, start_date,
                      benchmark_key, max_weight, rebalance_band, is_demo,
                      owner_user_id, risk_free_rate, fee_rate, slippage_rate, stamp_duty_rate,
                      result_version, data_as_of_date
               FROM bp_portfolio WHERE portfolio_id = %s""",
            (pid,),
        )
        r = cur.fetchone()
        if not r:
            raise KeyError(f"组合不存在: {pid}")
        cur.execute(
            "SELECT symbol, source, quadrant, display_name FROM bp_portfolio_asset "
            "WHERE portfolio_id = %s ORDER BY sort_order",
            (pid,),
        )
        assets = [
            {"symbol": a[0], "source": a[1], "quadrant": a[2], "display_name": a[3]}
            for a in cur.fetchall()
        ]
    return PortfolioDef(
        portfolio_id=r[0], name=r[1], description=r[2] or "组合描述",
        method=r[3], ratio=r[4], lookback_days=r[5],
        start_date=r[6], benchmark_key=r[7],
        max_weight=float(r[8]) if r[8] is not None else None,
        rebalance_band=float(r[9]), is_demo=r[10],
        owner_user_id=r[11],
        risk_free_rate=float(r[12] or 0),
        fee_rate=float(r[13] or 0),
        slippage_rate=float(r[14] or 0),
        stamp_duty_rate=float(r[15] or 0),
        result_version=int(r[16] or 1),
        data_as_of_date=r[17],
        assets=assets,
    )


def _resolve_benchmark_key(key: str) -> str:
    return key if key in BENCHMARKS else DEFAULT_BENCHMARK_KEY


def _insert_portfolio_assets(
    cur: psycopg.Cursor, pid: int, assets: list
) -> None:
    for i, a in enumerate(assets):
        cur.execute(
            """INSERT INTO bp_portfolio_asset
                 (portfolio_id, symbol, source, quadrant, display_name, sort_order)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (pid, a.symbol, a.source, a.quadrant, a.display_name, i),
        )


def count_unique_assets(assets: list) -> int:
    return len(_unique_asset_pairs([{"symbol": a.symbol, "source": a.source} for a in assets]))


def create_portfolio(conn: psycopg.Connection, data: CreatePortfolioIn, owner_user_id: Optional[int] = None) -> int:
    bkey = _resolve_benchmark_key(data.benchmark_key)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bp_portfolio
                 (name, description, method, ratio, lookback_days, start_date,
                  benchmark_key, max_weight, rebalance_band, risk_free_rate,
                  fee_rate, slippage_rate, stamp_duty_rate, owner_user_id, created_by, updated_by, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running')
               RETURNING portfolio_id""",
            (data.name, data.description, data.method, data.ratio, data.lookback_days, data.start_date,
             bkey, data.max_weight, data.rebalance_band, data.risk_free_rate or 0.0,
             data.fee_rate, data.slippage_rate, data.stamp_duty_rate, owner_user_id, owner_user_id, owner_user_id),
        )
        pid = cur.fetchone()[0]
        _insert_portfolio_assets(cur, pid, data.assets)
    return pid


def update_portfolio_meta(
    conn: psycopg.Connection, pid: int, name: str, description: str,
    updater_user_id: Optional[int] = None,
) -> None:
    """仅更新名称/描述, 不改动 assets/status, 不触发回测。"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_portfolio SET
                 name=%s, description=%s,
                 updated_by=COALESCE(%s, updated_by), updated_at=now()
               WHERE portfolio_id=%s""",
            (name, description, updater_user_id, pid),
        )
        if cur.rowcount == 0:
            raise KeyError(f"组合不存在: {pid}")


def update_portfolio(
    conn: psycopg.Connection, pid: int, data: UpdatePortfolioIn, updater_user_id: Optional[int] = None
) -> None:
    bkey = _resolve_benchmark_key(data.benchmark_key)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_portfolio SET
                 name=%s, description=%s, method=%s, ratio=%s, lookback_days=%s, start_date=%s,
                 benchmark_key=%s, max_weight=%s, rebalance_band=%s,
                 risk_free_rate=%s, fee_rate=%s, slippage_rate=%s, stamp_duty_rate=%s,
                 updated_by=COALESCE(%s, updated_by),
                 status='running', error=NULL, updated_at=now()
               WHERE portfolio_id=%s""",
            (data.name, data.description, data.method, data.ratio, data.lookback_days, data.start_date,
             bkey, data.max_weight, data.rebalance_band,
             data.risk_free_rate or 0.0, data.fee_rate, data.slippage_rate, data.stamp_duty_rate,
             updater_user_id, pid),
        )
        if cur.rowcount == 0:
            raise KeyError(f"组合不存在: {pid}")
        cur.execute("DELETE FROM bp_portfolio_asset WHERE portfolio_id = %s", (pid,))
        _insert_portfolio_assets(cur, pid, data.assets)


def list_portfolios(conn: psycopg.Connection, user_id: Optional[int] = None, is_admin: bool = False) -> list[dict]:
    # 当前用户的自定义顺序优先; 未排序的按 portfolio_id 降序兜底。NULL 排到最后。
    order_clause = (
        "ORDER BY p.is_demo DESC, COALESCE(o.display_order, 2147483647) ASC, p.portfolio_id DESC"
    )
    cols = (
        "p.portfolio_id, p.name, p.method, p.ratio, p.start_date, "
        "p.effective_start_date, p.is_demo, p.status, p.owner_user_id"
    )
    with conn.cursor() as cur:
        if is_admin:
            cur.execute(
                f"""SELECT {cols}
                    FROM bp_portfolio p
                    LEFT JOIN bp_user_portfolio_order o
                      ON o.portfolio_id = p.portfolio_id AND o.user_id = %s
                    {order_clause}""",
                (user_id,),
            )
        elif user_id is not None:
            cur.execute(
                f"""SELECT {cols}
                    FROM bp_portfolio p
                    LEFT JOIN bp_user_portfolio_order o
                      ON o.portfolio_id = p.portfolio_id AND o.user_id = %s
                    WHERE p.is_demo = TRUE OR p.owner_user_id = %s
                    {order_clause}""",
                (user_id, user_id),
            )
        else:
            cur.execute(
                """SELECT portfolio_id, name, method, ratio, start_date,
                          effective_start_date, is_demo, status, owner_user_id
                   FROM bp_portfolio
                   WHERE is_demo = TRUE
                   ORDER BY is_demo DESC, portfolio_id DESC"""
            )
        return [
            {"portfolio_id": r[0], "name": r[1], "method": r[2], "ratio": r[3],
             "start_date": r[4], "effective_start_date": r[5], "is_demo": r[6],
             "status": r[7], "owner_user_id": r[8]}
            for r in cur.fetchall()
        ]


def reorder_portfolios(conn: psycopg.Connection, user_id: int, ordered_ids: list[int]) -> None:
    """保存当前用户的组合下拉顺序; 仅对其可见的组合生效。"""
    if user_id is None:
        raise ValueError("缺少用户")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT portfolio_id FROM bp_portfolio
               WHERE is_demo = TRUE OR owner_user_id = %s
                  OR EXISTS (SELECT 1 FROM bp_user WHERE user_id=%s AND role='admin')""",
            (user_id, user_id),
        )
        visible = {r[0] for r in cur.fetchall()}
        for order, pid in enumerate(ordered_ids):
            if pid not in visible:
                continue
            cur.execute(
                """INSERT INTO bp_user_portfolio_order (user_id, portfolio_id, display_order)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id, portfolio_id)
                   DO UPDATE SET display_order = EXCLUDED.display_order, updated_at = now()""",
                (user_id, pid, order),
            )


# ---------------------------------------------------------------------
# 回测编排
# ---------------------------------------------------------------------
def run_and_save(
    conn: psycopg.Connection, pid: int, settings: ApiSettings, task_id: Optional[str] = None
) -> None:
    """对已存在的组合执行回测并落库; 预计算全部 4 种方法; 失败则置 status=error。"""
    pdef = _read_def(conn, pid)
    try:
        task_total = TASK_TOTAL_STEPS
        tasking.update_progress(conn, task_id, 1, task_total, "步骤 1/6：加载行情数据与组合参数")
        conn.commit()

        def progress(done: int, total: int, msg: str) -> None:
            tasking.update_progress(conn, task_id, min(done, total), total, msg)
            conn.commit()

        computed, prices = _compute(conn, pdef, settings, progress)  # {method: (result, metrics)}, 价格面板
        tasking.update_progress(conn, task_id, task_total - 1, task_total, "步骤 6/6：写入回测结果与绩效归因")

        default_method = pdef.method if pdef.method in computed else next(iter(computed))
        eff = computed[default_method][0].effective_start
        # 预计算候选基准净值(method 无关, 用默认方法的 nav 日期)
        dates = list(computed[default_method][0].nav.index)
        bench_navs = _compute_benchmark_navs(conn, dates)

        # 绩效归因复用资料: 资产日收益 + 配置基准日收益 + 名称/象限映射
        asset_returns = prices.pct_change()
        bench_key = pdef.benchmark_key if pdef.benchmark_key in bench_navs else (
            next(iter(bench_navs), None)
        )
        bench_ret = bench_navs[bench_key]["ret"] if bench_key in bench_navs else None
        name_map = {asset_key(a["symbol"], a["source"]): (a["display_name"] or a["symbol"]) for a in pdef.assets}
        quad_map = _asset_quadrants(pdef.assets)

        for method, (result, metrics) in computed.items():
            _save_results(conn, pdef, method, result, metrics)
            try:
                attr = compute_attribution(
                    result.daily_weights, asset_returns, bench_ret, result.nav["nav"],
                    [{"trade_date": rb.trade_date, "reason": rb.reason} for rb in result.rebalances],
                    name_map, quad_map,
                )
                _save_attribution(conn, pid, method, attr)
            except Exception:  # noqa: BLE001 - 归因失败不应阻断回测落库
                logger.exception("绩效归因计算失败 pid=%s method=%s", pid, method)

        _save_benchmarks(conn, pid, bench_navs)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bp_portfolio SET status='done', error=NULL, effective_start_date=%s, "
                "result_version=result_version+1, result_updated_at=now(), data_as_of_date=%s "
                "WHERE portfolio_id=%s",
                (eff, dates[-1] if dates else eff, pid),
            )
            cur.execute(
                """INSERT INTO bp_portfolio_update_state
                     (portfolio_id, last_result_trade_date, last_data_trade_date, last_task_id)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (portfolio_id) DO UPDATE SET
                     last_result_trade_date=EXCLUDED.last_result_trade_date,
                     last_data_trade_date=EXCLUDED.last_data_trade_date,
                     last_task_id=EXCLUDED.last_task_id,
                     updated_at=now()""",
                (pid, dates[-1] if dates else eff, dates[-1] if dates else eff, task_id),
            )
        tasking.update_progress(conn, task_id, task_total, task_total, "回测完成（6/6）")
        cache.delete_pattern(f"portfolio_result:{pid}:*")
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bp_portfolio SET status='error', error=%s WHERE portfolio_id=%s",
                (str(exc)[:2000], pid),
            )
        conn.commit()
        raise


def _compute(
    conn: psycopg.Connection, pdef: PortfolioDef, settings: ApiSettings, progress_cb=None
) -> tuple[dict[str, tuple[BacktestResult, dict]], pd.DataFrame]:
    """对全部 4 种方法回测(价格面板/基准只加载一次)。

    返回 ({method: (result, metrics)}, 价格面板 prices) —— prices 供绩效归因复用。
    """
    pairs = _unique_asset_pairs(pdef.assets)
    panel = load_price_panel(conn, pairs)

    quadrant_assets = build_quadrant_assets(pdef.assets)
    keys = [asset_key(s, src) for s, src in pairs]
    prices = panel[keys]

    # 回测内置基准固定用沪深300, 以保证信息比率口径统一(展示基准另行预计算)
    ir_leg = BENCHMARKS[INFO_RATIO_BENCH]["legs"][0]
    bench = _load_series(conn, ir_leg[1], ir_leg[2])
    if bench.empty:
        raise ValueError(f"信息比率基准 {INFO_RATIO_BENCH} 无清洗数据")

    method_base = {m: i * 100 + 1 for i, m in enumerate(BACKTEST_METHODS)}

    def compute_one(method: str) -> tuple[str, tuple[BacktestResult, dict], float]:
        idx = BACKTEST_METHODS.index(method)
        step = _step_label(method, idx)
        t0 = time.perf_counter()
        if progress_cb:
            progress_cb(method_base[method], 402, step)

        def cb(cur: int, total: int, msg: str) -> None:
            if progress_cb:
                pct = cur / max(total, 1)
                sub = f"（{int(pct * 100)}%）" if msg else ""
                progress_cb(method_base[method] + int(pct * 80), 402, f"{step}{sub}")

        result = run_backtest(
            prices=prices, benchmark=bench, quadrant_assets=quadrant_assets,
            method=method, ratio=pdef.ratio, lookback=pdef.lookback_days,
            min_window=settings.min_window, max_weight=pdef.max_weight,
            rebalance_band=pdef.rebalance_band, risk_free=pdef.risk_free_rate,
            fee_rate=pdef.fee_rate, slippage_rate=pdef.slippage_rate,
            stamp_duty_rate=pdef.stamp_duty_rate,
            trading_days=settings.trading_days, user_start=pdef.start_date,
            progress_cb=cb,
        )
        nav_series = result.nav["nav"]
        bench_series = result.nav["benchmark_nav"]
        metrics = {
            "portfolio": compute_metrics(nav_series, bench_series, pdef.risk_free_rate, settings.trading_days),
            "benchmark": compute_metrics(bench_series, None, pdef.risk_free_rate, settings.trading_days),
        }
        elapsed = time.perf_counter() - t0
        if progress_cb:
            progress_cb(method_base[method] + 99, 402, f"{step} 完成，用时 {elapsed:.1f}s")
        return method, (result, metrics), elapsed

    cpu_count = os.cpu_count() or 2
    max_cpu_fraction = float(os.getenv("BP_MAX_CPU_FRACTION", "0.75") or "0.75")
    cpu_budget = max(1, int(cpu_count * max_cpu_fraction))
    default_workers = max(1, min(4, cpu_budget - 1 if cpu_budget > 1 else 1))
    workers = max(1, int(os.getenv("BP_BACKTEST_METHOD_WORKERS", str(default_workers)) or str(default_workers)))
    workers = min(workers, len(BACKTEST_METHODS))
    out: dict[str, tuple[BacktestResult, dict]] = {}
    # Celery prefork worker 是守护进程, 禁止 fork 子进程; 此时回退到线程池
    use_process = (
        workers > 1
        and platform.system().lower() != "windows"
        and not _in_daemon_process()
    )
    if workers == 1:
        for method in BACKTEST_METHODS:
            k, v, _elapsed = compute_one(method)
            out[k] = v
    else:
        job_args = [
            (
                method,
                prices,
                bench,
                quadrant_assets,
                pdef.ratio,
                pdef.lookback_days,
                settings.min_window,
                pdef.max_weight,
                pdef.rebalance_band,
                pdef.risk_free_rate,
                pdef.fee_rate,
                pdef.slippage_rate,
                pdef.stamp_duty_rate,
                settings.trading_days,
                pdef.start_date,
            )
            for method in BACKTEST_METHODS
        ]
        executor_cls = ProcessPoolExecutor if use_process else ThreadPoolExecutor
        with executor_cls(max_workers=workers) as ex:
            futures = [ex.submit(_compute_method_job, args) for args in job_args]
            for fut in as_completed(futures):
                k, v, elapsed = fut.result()
                out[k] = v
                if progress_cb:
                    progress_cb(method_base[k] + 99, 402, f"{_step_label(k, BACKTEST_METHODS.index(k))} 完成，用时 {elapsed:.1f}s")
    return out, prices


def _compute_benchmark_navs(conn: psycopg.Connection, dates: list) -> dict[str, pd.DataFrame]:
    """在给定交易日序列上计算每个候选基准的单位净值(起点=1.0)。"""
    idx = pd.Index(dates)
    out: dict[str, pd.DataFrame] = {}
    for key, spec in BENCHMARKS.items():
        total_ret = pd.Series(0.0, index=idx)
        ok = True
        for w, sym, src in spec["legs"]:
            s = _load_series(conn, sym, src)
            if s.empty:
                ok = False
                break
            close = s.reindex(idx).ffill().bfill()
            total_ret = total_ret.add(close.pct_change().fillna(0.0) * w, fill_value=0.0)
        if not ok:
            continue
        total_ret.iloc[0] = 0.0
        nav = (1.0 + total_ret).cumprod()
        out[key] = pd.DataFrame({"nav": nav, "ret": total_ret})
    return out


def _save_benchmarks(
    conn: psycopg.Connection, pid: int, bench_navs: dict[str, pd.DataFrame]
) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bp_backtest_benchmark WHERE portfolio_id=%s", (pid,))
        for key, df in bench_navs.items():
            rows = [
                (pid, key, idx, float(row["nav"]),
                 None if pd.isna(row["ret"]) else float(row["ret"]))
                for idx, row in df.iterrows()
            ]
            cur.executemany(
                "INSERT INTO bp_backtest_benchmark (portfolio_id, benchmark_key, trade_date, nav, ret) "
                "VALUES (%s,%s,%s,%s,%s)",
                rows,
            )


def _save_attribution(conn: psycopg.Connection, pid: int, method: str, attribution: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bp_backtest_attribution (portfolio_id, method, payload)
               VALUES (%s, %s, %s)
               ON CONFLICT (portfolio_id, method)
               DO UPDATE SET payload = EXCLUDED.payload""",
            (pid, method, Json(_json_safe(attribution))),
        )


def _save_results(
    conn: psycopg.Connection, pdef: PortfolioDef, method: str,
    result: BacktestResult, metrics: dict,
) -> None:
    pid = pdef.portfolio_id
    name_map = {asset_key(a["symbol"], a["source"]): (a["display_name"] or a["symbol"]) for a in pdef.assets}
    quad_map = _asset_quadrants(pdef.assets)

    with conn.cursor() as cur:
        # 幂等: 按 (pid, method) 清理旧结果
        cur.execute("DELETE FROM bp_backtest_nav WHERE portfolio_id=%s AND method=%s", (pid, method))
        cur.execute("DELETE FROM bp_backtest_rebalance WHERE portfolio_id=%s AND method=%s", (pid, method))
        cur.execute("DELETE FROM bp_backtest_metric WHERE portfolio_id=%s AND method=%s", (pid, method))
        cur.execute("DELETE FROM bp_backtest_cov WHERE portfolio_id=%s AND method=%s", (pid, method))

        nav_rows = [
            (pid, method, idx, float(row["nav"]),
             None if pd.isna(row["benchmark_nav"]) else float(row["benchmark_nav"]),
             None if pd.isna(row["ret"]) else float(row["ret"]),
             None if pd.isna(row["bench_ret"]) else float(row["bench_ret"]))
            for idx, row in result.nav.iterrows()
        ]
        cur.executemany(
            "INSERT INTO bp_backtest_nav (portfolio_id, method, trade_date, nav, benchmark_nav, ret, bench_ret) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            nav_rows,
        )

        for rb in result.rebalances:
            cur.execute(
                """INSERT INTO bp_backtest_rebalance
                     (portfolio_id, method, trade_date, reason, target_weights, prev_weights,
                      delta, quadrant_weights, max_deviation)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (pid, method, rb.trade_date, rb.reason, Json(_json_safe(rb.target_weights)),
                 Json(_json_safe(rb.prev_weights)) if rb.prev_weights else None,
                 Json(_json_safe(rb.delta)) if rb.delta else None,
                 Json(_json_safe(rb.quadrant_weights)) if rb.quadrant_weights else None,
                 rb.max_deviation),
            )

        for scope in ("portfolio", "benchmark"):
            cur.execute(
                "INSERT INTO bp_backtest_metric (portfolio_id, method, scope, metrics) VALUES (%s,%s,%s,%s)",
                (pid, method, scope, Json(_json_safe(metrics[scope]))),
            )

        labels = [name_map.get(k, k) for k in result.corr_labels]
        cur.execute(
            """INSERT INTO bp_backtest_cov
                 (portfolio_id, method, as_of_date, labels, corr_matrix, cov_matrix,
                  optimal_weights, optimal_quadrant_weights)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (pid, method, result.as_of, Json(_json_safe(labels)),
             Json(_json_safe(result.corr_matrix)), Json(_json_safe(result.cov_matrix)),
             Json(_json_safe(result.end_optimal_target)),
             Json(_json_safe(result.end_optimal_quadrant_weights))),
        )


# ---------------------------------------------------------------------
# 结果读取
# ---------------------------------------------------------------------
def _build_holdings_list(
    weights: dict,
    name_map: dict[str, dict],
    quad_map: dict[str, list],
) -> list[dict]:
    return [
        {
            "key": k,
            "symbol": name_map.get(k, {}).get("symbol"),
            "source": name_map.get(k, {}).get("source"),
            "name": name_map.get(k, {}).get("display_name") or name_map.get(k, {}).get("symbol") or k,
            "quadrants": quad_map.get(k, []),
            "quadrant": quad_map.get(k, [None])[0] if quad_map.get(k) else None,
            "weight": w,
        }
        for k, w in sorted(weights.items(), key=lambda x: -x[1])
    ]


def get_portfolio_status(conn: psycopg.Connection, pid: int) -> dict:
    """轻量状态查询, 供轮询用。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, error, effective_start_date FROM bp_portfolio WHERE portfolio_id = %s",
            (pid,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"组合不存在: {pid}")
    return {
        "portfolio_id": pid,
        "status": row[0],
        "error": row[1],
        "effective_start_date": row[2],
    }


def get_portfolio_dict(conn: psycopg.Connection, pid: int) -> dict:
    pdef = _read_def(conn, pid)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT effective_start_date, status, error, result_updated_at FROM bp_portfolio WHERE portfolio_id=%s",
            (pid,),
        )
        eff, status, error, result_updated_at = cur.fetchone()
    return {
        "portfolio_id": pid, "name": pdef.name, "description": pdef.description,
        "method": pdef.method, "ratio": pdef.ratio,
        "lookback_days": pdef.lookback_days, "start_date": pdef.start_date,
        "effective_start_date": eff, "benchmark_key": pdef.benchmark_key,
        "benchmark_name": BENCHMARKS.get(pdef.benchmark_key, {}).get("name", pdef.benchmark_key),
        "rebalance_band": pdef.rebalance_band, "max_weight": pdef.max_weight,
        "risk_free_rate": pdef.risk_free_rate,
        "fee_rate": pdef.fee_rate,
        "slippage_rate": pdef.slippage_rate,
        "stamp_duty_rate": pdef.stamp_duty_rate,
        "is_demo": pdef.is_demo, "owner_user_id": pdef.owner_user_id,
        "result_version": pdef.result_version, "result_updated_at": result_updated_at,
        "data_as_of_date": pdef.data_as_of_date,
        "status": status, "error": error, "assets": pdef.assets,
    }


def get_result_version(conn: psycopg.Connection, pid: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT result_version FROM bp_portfolio WHERE portfolio_id=%s", (pid,))
        row = cur.fetchone()
        if not row:
            raise KeyError(f"组合不存在: {pid}")
        return int(row[0] or 1)


def can_view_portfolio(conn: psycopg.Connection, pid: int, user_id: Optional[int], is_admin: bool) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT is_demo, owner_user_id FROM bp_portfolio WHERE portfolio_id=%s", (pid,))
        row = cur.fetchone()
    if not row:
        raise KeyError(f"组合不存在: {pid}")
    return bool(row[0]) or is_admin or (user_id is not None and row[1] == user_id)


def can_edit_portfolio(conn: psycopg.Connection, pid: int, user_id: Optional[int], is_admin: bool) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT is_demo, owner_user_id FROM bp_portfolio WHERE portfolio_id=%s", (pid,))
        row = cur.fetchone()
    if not row:
        raise KeyError(f"组合不存在: {pid}")
    if is_admin:
        return True
    return (not row[0]) and user_id is not None and row[1] == user_id


def count_user_portfolios(conn: psycopg.Connection, user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM bp_portfolio WHERE owner_user_id=%s AND is_demo=FALSE",
            (user_id,),
        )
        return int(cur.fetchone()[0])


def get_user_portfolio_limit(conn: psycopg.Connection, user_id: int) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT role, portfolio_limit FROM bp_user WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
    if not row or row[0] == "admin":
        return None
    return int(row[1] if row[1] is not None else 3)


def copy_portfolio(
    conn: psycopg.Connection, pid: int, owner_user_id: int, new_name: Optional[str] = None
) -> int:
    p = _read_def(conn, pid)
    name = (new_name or "").strip() or f"{p.name} 副本"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bp_portfolio
                 (name, description, method, ratio, lookback_days, start_date,
                  benchmark_key, max_weight, rebalance_band, risk_free_rate,
                  fee_rate, slippage_rate, stamp_duty_rate, owner_user_id, created_by, updated_by, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')
               RETURNING portfolio_id""",
            (
                name, p.description, p.method, p.ratio, p.lookback_days, p.start_date,
                p.benchmark_key, p.max_weight, p.rebalance_band, p.risk_free_rate,
                p.fee_rate, p.slippage_rate, p.stamp_duty_rate, owner_user_id, owner_user_id, owner_user_id,
            ),
        )
        new_pid = cur.fetchone()[0]
        for i, a in enumerate(p.assets):
            cur.execute(
                """INSERT INTO bp_portfolio_asset
                     (portfolio_id, symbol, source, quadrant, display_name, sort_order)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (new_pid, a["symbol"], a["source"], a["quadrant"], a["display_name"], i),
            )
    return new_pid


def get_result(
    conn: psycopg.Connection, pid: int,
    method: Optional[str] = None, benchmark: Optional[str] = None,
) -> dict:
    pdef = _read_def(conn, pid)
    portfolio = get_portfolio_dict(conn, pid)
    name_map = {asset_key(a["symbol"], a["source"]): a for a in pdef.assets}
    quad_map = _asset_quadrants(pdef.assets)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT method FROM bp_backtest_nav WHERE portfolio_id=%s", (pid,)
        )
        available = sorted({r[0] for r in cur.fetchall()},
                           key=lambda m: BACKTEST_METHODS.index(m) if m in BACKTEST_METHODS else 99)
        sel = method if (method and method in available) else (
            pdef.method if pdef.method in available else (available[0] if available else pdef.method)
        )

        # 可用基准
        cur.execute(
            "SELECT DISTINCT benchmark_key FROM bp_backtest_benchmark WHERE portfolio_id=%s", (pid,)
        )
        bench_keys = sorted({r[0] for r in cur.fetchall()},
                            key=lambda k: list(BENCHMARKS).index(k) if k in BENCHMARKS else 99)
        bsel = benchmark if (benchmark and benchmark in bench_keys) else (
            pdef.benchmark_key if pdef.benchmark_key in bench_keys else (bench_keys[0] if bench_keys else pdef.benchmark_key)
        )

        # 所选基准净值序列
        cur.execute(
            "SELECT trade_date, nav, ret FROM bp_backtest_benchmark "
            "WHERE portfolio_id=%s AND benchmark_key=%s ORDER BY trade_date",
            (pid, bsel),
        )
        bench_map = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        cur.execute(
            "SELECT trade_date, nav, ret FROM bp_backtest_nav "
            "WHERE portfolio_id=%s AND method=%s ORDER BY trade_date",
            (pid, sel),
        )
        nav = [
            {"trade_date": r[0], "nav": r[1],
             "benchmark_nav": bench_map.get(r[0], (None, None))[0],
             "ret": r[2], "bench_ret": bench_map.get(r[0], (None, None))[1]}
            for r in cur.fetchall()
        ]

        cur.execute(
            """SELECT trade_date, reason, target_weights, prev_weights, delta,
                      quadrant_weights, max_deviation
               FROM bp_backtest_rebalance WHERE portfolio_id=%s AND method=%s ORDER BY trade_date""",
            (pid, sel),
        )
        rebalances = [
            {"trade_date": r[0], "reason": r[1], "target_weights": r[2], "prev_weights": r[3],
             "delta": r[4], "quadrant_weights": r[5], "max_deviation": r[6]}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT scope, metrics FROM bp_backtest_metric WHERE portfolio_id=%s AND method=%s",
            (pid, sel),
        )
        metrics = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            "SELECT method, metrics FROM bp_backtest_metric "
            "WHERE portfolio_id=%s AND scope='portfolio'",
            (pid,),
        )
        method_metric_rows = cur.fetchall()

        cur.execute(
            "SELECT as_of_date, labels, corr_matrix, cov_matrix, optimal_weights, optimal_quadrant_weights "
            "FROM bp_backtest_cov WHERE portfolio_id=%s AND method=%s",
            (pid, sel),
        )
        cov_row = cur.fetchone()

        cur.execute(
            "SELECT payload FROM bp_backtest_attribution WHERE portfolio_id=%s AND method=%s",
            (pid, sel),
        )
        attr_row = cur.fetchone()
    attribution = attr_row[0] if attr_row else None
    corr = (
        {"labels": cov_row[1], "matrix": cov_row[2], "cov": cov_row[3]}
        if cov_row else {"labels": [], "matrix": [], "cov": []}
    )
    optimal_holdings = None
    if cov_row and cov_row[4]:
        optimal_holdings = {
            "as_of_date": cov_row[0],
            "holdings": _build_holdings_list(cov_row[4], name_map, quad_map),
            "quadrant_weights": cov_row[5],
        }

    # 基准指标按所选基准序列即时计算(组合指标的信息比率仍固定为沪深300)
    from .quant.metrics import compute_metrics as _cm, max_drawdown_recovery_days as _mdd_days
    if nav:
        pser = pd.Series({r["trade_date"]: r["nav"] for r in nav}).sort_index()
        if "portfolio" in metrics:
            metrics["portfolio"]["max_drawdown_recovery_days"] = _mdd_days(pser)
    if bench_map:
        bser = pd.Series({d: v[0] for d, v in bench_map.items()}).sort_index()
        metrics["benchmark"] = _cm(bser, None, pdef.risk_free_rate)
        metrics["benchmark"]["max_drawdown_recovery_days"] = _mdd_days(bser)

    summaries = []
    best_method = None
    best_total = None
    for method_key, mm in method_metric_rows:
        total = (mm or {}).get("total_return")
        if total is not None and (best_total is None or total > best_total):
            best_total = total
            best_method = method_key
    for method_key, mm in sorted(
        method_metric_rows,
        key=lambda r: BACKTEST_METHODS.index(r[0]) if r[0] in BACKTEST_METHODS else 99,
    ):
        mm = mm or {}
        summaries.append(
            {
                "method": method_key,
                "total_return": mm.get("total_return"),
                "annualized_return": mm.get("annualized_return"),
                "sharpe": mm.get("sharpe"),
                "is_default": method_key == pdef.method,
                "is_best_total_return": method_key == best_method,
            }
        )

    # 当期持仓 = 最近一次再平衡的目标权重(「最近」调仓日)
    holdings: list[dict] = []
    quadrant_weights = None
    if rebalances:
        latest = rebalances[-1]
        quadrant_weights = latest["quadrant_weights"]
        holdings = _build_holdings_list(latest["target_weights"], name_map, quad_map)

    return {
        "portfolio": portfolio, "nav": nav, "rebalances": rebalances,
        "metrics": metrics, "holdings": holdings,
        "optimal_holdings": optimal_holdings,
        "quadrant_weights": quadrant_weights, "corr": corr,
        "attribution": attribution,
        "method": sel, "available_methods": available,
        "method_summaries": summaries,
        "benchmark": bsel,
        "benchmark_name": BENCHMARKS.get(bsel, {}).get("name", bsel),
        "benchmarks": [{"key": k, "name": BENCHMARKS.get(k, {}).get("name", k)} for k in bench_keys],
    }


def get_demo_id(conn: psycopg.Connection, portfolio_id: Optional[int] = None) -> Optional[int]:
    """返回示例组合 id; 指定 portfolio_id 时须为 demo, 否则取最早创建的 demo。"""
    with conn.cursor() as cur:
        if portfolio_id is not None:
            cur.execute(
                "SELECT portfolio_id FROM bp_portfolio WHERE portfolio_id = %s AND is_demo = TRUE",
                (portfolio_id,),
            )
        else:
            cur.execute(
                "SELECT portfolio_id FROM bp_portfolio WHERE is_demo = TRUE "
                "ORDER BY portfolio_id ASC LIMIT 1"
            )
        r = cur.fetchone()
        return r[0] if r else None


def set_portfolio_demo(conn: psycopg.Connection, pid: int, is_demo: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bp_portfolio SET is_demo = %s, updated_at = now() WHERE portfolio_id = %s",
            (is_demo, pid),
        )
        if cur.rowcount == 0:
            raise KeyError(f"组合不存在: {pid}")


def list_data_sources(conn: psycopg.Connection) -> list[dict]:
    """行情源枚举(供资产管理下拉与 symbol 书写提示)。"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT code, description, asset_class, symbol_hint,
                      supports_date_range, is_enabled, vendor
               FROM bp_data_source
               ORDER BY asset_class, code"""
        )
        return [
            {
                "code": r[0],
                "description": r[1],
                "asset_class": r[2],
                "symbol_hint": r[3],
                "supports_date_range": r[4],
                "is_enabled": r[5],
                "vendor": r[6],
            }
            for r in cur.fetchall()
        ]


def list_admin_assets(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.symbol, c.source, c.category, c.name, c.start_date, c.is_deleted,
                      s.asset_class, s.vendor,
                      st.last_raw_date, st.last_clean_date, st.raw_rows, st.clean_rows,
                      st.last_success_at, st.last_error, st.last_probe_ms,
                      c.is_selectable, c.extra_params->>'adjust' AS adjust
               FROM bp_index_config c
               JOIN bp_data_source s ON s.code = c.source
               LEFT JOIN bp_asset_data_status st
                 ON st.symbol = c.symbol AND st.source = c.source
               ORDER BY c.is_deleted, s.asset_class, c.symbol"""
        )
        return [
            {
                "symbol": r[0],
                "source": r[1],
                "category": r[2],
                "name": r[3],
                "start_date": r[4],
                "is_deleted": r[5],
                "asset_class": r[6],
                "vendor": r[7],
                "last_raw_date": r[8],
                "last_clean_date": r[9],
                "raw_rows": r[10] or 0,
                "clean_rows": r[11] or 0,
                "last_success_at": r[12],
                "last_error": r[13],
                "last_probe_ms": r[14],
                "is_selectable": bool(r[15]),
                "adjust": r[16],
            }
            for r in cur.fetchall()
        ]


def upsert_asset_config(conn: psycopg.Connection, data) -> None:
    # adjust 写入 extra_params(仅 ETF 类目); 用 jsonb || 合并以保留既有键(如 bond 的 indicator),
    # adjust=None 时 patch='{}' 即不动既有 extra_params。
    #
    # 在 Python 侧构造 jsonb patch 串(而非 SQL 的 jsonb_build_object): %(adjust)s 若同时出现在
    # jsonb_build_object(anyelement) 与 IS NULL 两类上下文, PG 无法推断参数类型 →
    # "IndeterminateDatatype: could not determine data type of parameter"。改用 %(extra_patch)s::jsonb
    # 显式定型, 规避多态推断。
    import json as _json
    extra_patch = _json.dumps({"adjust": data.adjust}) if data.adjust else "{}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bp_index_config
                 (symbol, source, category, name, start_date, is_deleted, extra_params)
               VALUES (%(symbol)s, %(source)s, %(category)s, %(name)s, %(start_date)s,
                       %(is_deleted)s, %(extra_patch)s::jsonb)
               ON CONFLICT (symbol, source) DO UPDATE SET
                 category = EXCLUDED.category,
                 name = EXCLUDED.name,
                 start_date = EXCLUDED.start_date,
                 is_deleted = EXCLUDED.is_deleted,
                 extra_params = COALESCE(bp_index_config.extra_params, '{}'::jsonb) || %(extra_patch)s::jsonb,
                 updated_at = now()""",
            {
                "symbol": data.symbol, "source": data.source, "category": data.category,
                "name": data.name, "start_date": data.start_date,
                "is_deleted": data.is_deleted, "extra_patch": extra_patch,
            },
        )


def asset_probe_ok(conn: psycopg.Connection, symbol: str, source: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT last_probe_ms, last_error
               FROM bp_asset_data_status
               WHERE symbol=%s AND source=%s""",
            (symbol, source),
        )
        row = cur.fetchone()
    return bool(row and row[0] is not None and row[1] is None)


def soft_delete_asset(conn: psycopg.Connection, source: str, symbol: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bp_index_config SET is_deleted=1, updated_at=now() WHERE source=%s AND symbol=%s",
            (source, symbol),
        )
        if cur.rowcount == 0:
            raise KeyError(f"资产不存在: {symbol}@{source}")


def set_asset_selectable(conn: psycopg.Connection, source: str, symbol: str, selectable: bool) -> None:
    """停用/启用: 仅影响 builder 可选性, 不影响 ingest 定时更新。"""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bp_index_config SET is_selectable=%s, updated_at=now() WHERE source=%s AND symbol=%s",
            (selectable, source, symbol),
        )
        if cur.rowcount == 0:
            raise KeyError(f"资产不存在: {symbol}@{source}")


def refresh_asset_status(conn: psycopg.Connection, symbol: str, source: str, error: Optional[str] = None, probe_ms: Optional[int] = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(trade_date), COUNT(*) FROM bp_index_quote_daily WHERE symbol=%s AND source=%s",
            (symbol, source),
        )
        raw_date, raw_rows = cur.fetchone()
        cur.execute(
            "SELECT MAX(trade_date), COUNT(*) FROM bp_quote_clean WHERE symbol=%s AND source=%s",
            (symbol, source),
        )
        clean_date, clean_rows = cur.fetchone()
        success_at = datetime.now(timezone.utc) if error is None else None
        cur.execute(
            """INSERT INTO bp_asset_data_status
                 (symbol, source, last_raw_date, last_clean_date, raw_rows, clean_rows,
                  last_success_at, last_error, last_probe_ms)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (symbol, source) DO UPDATE SET
                 last_raw_date=EXCLUDED.last_raw_date,
                 last_clean_date=EXCLUDED.last_clean_date,
                 raw_rows=EXCLUDED.raw_rows,
                 clean_rows=EXCLUDED.clean_rows,
                 last_success_at=COALESCE(EXCLUDED.last_success_at, bp_asset_data_status.last_success_at),
                 last_error=EXCLUDED.last_error,
                 last_probe_ms=EXCLUDED.last_probe_ms,
                 updated_at=now()""",
            (symbol, source, raw_date, clean_date, raw_rows or 0, clean_rows or 0, success_at, error, probe_ms),
        )


def delete_portfolio(conn: psycopg.Connection, pid: int) -> None:
    """删除组合(含 demo); 结果表通过 FK ON DELETE CASCADE 级联清理。"""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bp_portfolio WHERE portfolio_id = %s", (pid,))
    conn.commit()
