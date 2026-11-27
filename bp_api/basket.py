"""一篮子资产风险平价 — API 端点（register_routes 模式）。

两个只读计算端点（不落库、不触发任务）：
  POST /api/basket/optimize   给定资产池 → 6 方法之一的当前目标权重 + 诊断
  POST /api/basket/backtest   同一资产池 + 再平衡漂移带 → 净值曲线/年化/回撤/换手/贡献

数据只读 `bp_quote_clean`（经 `repositories.load_price_panel` 构建价格面板），
鉴权与估值接口一致：`Depends(auth.optional_user)`，匿名可调用。
main.py 的路由注册由主控完成，本模块只提供 `register_routes(app)`。
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException

from . import auth, db, repositories as repo
from .quant.basket import (
    DEFAULT_FEE_RATE,
    DEFAULT_SLIPPAGE_RATE,
    DEFAULT_STAMP_DUTY_RATE,
    METHODS,
    optimize,
    run_basket_backtest,
    summarize_returns,
)
from .repositories import _json_safe
from .schemas import BasketBacktestIn, BasketOptimizeIn
from .settings import load_settings


# ---------------------------------------------------------------------------
# 入参校验 / 数据准备
# ---------------------------------------------------------------------------
def _pairs(payload) -> list[tuple[str, str]]:
    """去重并保持输入顺序；重复资产直接 400（权重含义会变得歧义）。"""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for a in payload.assets:
        key = (a.symbol, a.source)
        if key in seen:
            raise HTTPException(400, f"重复资产: {a.symbol}@{a.source}")
        seen.add(key)
        out.append(key)
    if not out:
        raise HTTPException(400, "至少选择一个资产")
    return out


def _keys(pairs: list[tuple[str, str]]) -> list[str]:
    return [f"{symbol}@{source}" for symbol, source in pairs]


def _validate_method(method: str) -> None:
    if method not in METHODS:
        raise HTTPException(
            400,
            f"未知优化方法 method={method}（可选: {', '.join(METHODS)}）",
        )


def _validate_risk_budget(payload, keys: list[str]) -> None:
    """risk_budget 只在 risk_budget 方法下生效；键须为 symbol@source，合计=1。"""
    if payload.method != "risk_budget" or payload.risk_budget is None:
        return
    if not payload.risk_budget:
        raise HTTPException(400, "risk_budget 不能为空")

    unknown = sorted(set(payload.risk_budget) - set(keys))
    if unknown:
        raise HTTPException(
            400, f"risk_budget 含未知资产: {', '.join(unknown)}"
        )

    total = 0.0
    for key, value in payload.risk_budget.items():
        try:
            fv = float(value)
        except (TypeError, ValueError):
            raise HTTPException(400, f"risk_budget[{key}] 必须是数值")
        if not math.isfinite(fv) or fv < 0:
            raise HTTPException(400, f"risk_budget[{key}] 必须是非负有限数")
        total += fv
    if abs(total - 1.0) > 1e-6:
        raise HTTPException(400, f"risk_budget 合计必须为 1（当前 {total:.6f}）")


def _load_panel(conn, pairs: list[tuple[str, str]]) -> pd.DataFrame:
    """只读清洗行情面板；缺数据 404，其余读取错误 400。"""
    try:
        panel = repo.load_price_panel(conn, pairs)
    except ValueError as exc:
        message = str(exc)
        if "无清洗行情数据" in message:
            raise HTTPException(404, message) from exc
        raise HTTPException(400, message) from exc
    if panel is None or panel.empty:
        raise HTTPException(400, "所选区间无清洗行情数据")
    return panel


def _slice_panel(panel: pd.DataFrame, end: Optional[date]) -> pd.DataFrame:
    return panel.loc[:end] if end is not None else panel


def _returns_from_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """日收益矩阵：ffill(左锚) + pct_change，首行无收益故丢弃。"""
    if panel.empty:
        return pd.DataFrame(index=panel.index)
    return panel.ffill().pct_change().iloc[1:]


def _iso_date(value) -> str:
    """日期统一输出为 ISO 字符串（兼容 date/datetime/Timestamp/普通值）。"""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _rounded_weights(weights: dict[str, float], ndigits: int = 10) -> dict[str, float]:
    """输出前清洗 NaN/Inf，并用最大项吸收舍入残差，保证合计≈1。"""
    out: dict[str, float] = {}
    for key, value in weights.items():
        try:
            fv = float(value)
        except (TypeError, ValueError):
            fv = 0.0
        out[key] = 0.0 if not math.isfinite(fv) else round(fv, ndigits)
    if out:
        total = sum(out.values())
        if abs(total - 1.0) > 1e-12:
            kmax = max(out, key=lambda k: abs(out[k]))
            out[kmax] += 1.0 - total
    return out


def _weight_rows(
    pairs: list[tuple[str, str]], keys: list[str], weights: np.ndarray
) -> list[dict]:
    values = _rounded_weights({k: float(v) for k, v in zip(keys, weights)})
    return [
        {"symbol": symbol, "source": source, "weight": values[key]}
        for (symbol, source), key in zip(pairs, keys)
    ]


def _split_key(key: str) -> tuple[str, str]:
    symbol, sep, source = key.rpartition("@")
    if not sep:
        return key, ""
    return symbol, source


def _asset_hash(columns) -> str:
    """资产列表指纹：排序后取 sha256 前 16 位（与列顺序无关）。

    前端可按同一规则（symbol@source 升序用 "\n" 连接、sha256 前 16 位）
    重建指纹，与 latest_result.params.asset_hash 比对，判断结果是否对应当前定义。
    """
    payload = "\n".join(sorted(str(key) for key in columns))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 服务端重算（供 POST /api/baskets/{id}/recompute 与 seed 脚本共用）
# ---------------------------------------------------------------------------
def build_latest_result(
    panel: pd.DataFrame,
    *,
    method: str,
    lookback_days: int,
    rebalance_band: float = 0.05,
    risk_free: float = 0.0,
    risk_budget: Optional[dict] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    trading_days: int = 244,
    min_window: int = 60,
    fee_rate: float = DEFAULT_FEE_RATE,
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
    stamp_duty_rate: float = DEFAULT_STAMP_DUTY_RATE,
) -> dict:
    """对已保存的篮子定义做一次同步回测，生成可落库的 latest_result 摘要。

    口径与 POST /api/basket/backtest 完全一致（复用 run_basket_backtest）：净值、
    年化收益/波动/回撤/夏普/换手、最近一次调仓目标权重与逐日净值。latest_result
    只能由本函数（服务端 recompute / seed --recompute）生成，避免前端伪造示例指标。
    """
    if method not in METHODS:
        raise ValueError(f"未知优化方法 method={method}")
    if panel is None or panel.empty:
        raise ValueError("所选区间无清洗行情数据")
    frame = panel.loc[:end] if end is not None else panel
    if frame.empty:
        raise ValueError("所选区间无清洗行情数据")
    try:
        lookback = int(lookback_days)
    except (TypeError, ValueError):
        lookback = 156
    lookback = max(2, lookback)
    result = run_basket_backtest(
        frame,
        method=method,
        lookback=lookback,
        min_window=min(int(min_window), lookback),
        rebalance_band=float(rebalance_band),
        risk_free=float(risk_free),
        risk_budget=risk_budget or None,
        trading_days=int(trading_days),
        fee_rate=float(fee_rate),
        slippage_rate=float(slippage_rate),
        stamp_duty_rate=float(stamp_duty_rate),
        user_start=start,
    )

    keys = list(frame.columns)
    pairs = [_split_key(str(key)) for key in keys]
    weights = _weight_rows(pairs, keys, np.array([result.latest_target.get(k, 0.0) for k in keys]))
    nav_rows = [
        {
            "trade_date": _iso_date(index),
            "nav": float(row["nav"]),
            "ret": float(row["ret"]),
        }
        for index, row in result.nav.iterrows()
    ]
    summary = {
        "method": method,
        # 参数指纹：供前端判断 latest_result 是否对应当前篮子定义（定义变更后旧
        # 结果应提示重算）。不改变既有顶层字段，只新增 params 子对象。
        "params": {
            "method": method,
            "lookback_days": lookback,
            "rebalance_band": float(rebalance_band),
            "risk_free": float(risk_free),
            "start": start.isoformat() if start is not None else None,
            "end": end.isoformat() if end is not None else None,
            "asset_hash": _asset_hash(frame.columns),
        },
        "as_of": nav_rows[-1]["trade_date"] if nav_rows else None,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "effective_start": _iso_date(result.effective_start),
        "lookback_days": lookback,
        "rebalance_band": float(rebalance_band),
        "risk_free": float(risk_free),
        "n_obs": int(result.n_obs),
        "trading_days": int(trading_days),
        "annualized_return": float(result.metrics["annualized_return"]),
        "annualized_vol": float(result.metrics["annualized_vol"]),
        "max_drawdown": float(result.metrics["max_drawdown"]),
        "sharpe": float(result.metrics["sharpe"]),
        "sortino": float(result.metrics["sortino"]),
        "calmar": float(result.metrics["calmar"]),
        "turnover": float(result.annualized_turnover),
        "turnover_total": float(result.total_turnover),
        "rebalance_count": len(result.rebalances),
        "fees": dict(result.fees),
        "assets": [{"symbol": symbol, "source": source} for symbol, source in pairs],
        "weights": weights,
        "nav": nav_rows,
    }
    return _json_safe(summary)


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------
def register_routes(app: FastAPI) -> None:
    settings = load_settings()
    trading_days = settings.trading_days
    default_min_window = settings.min_window

    @app.post("/api/basket/optimize")
    def basket_optimize(
        payload: BasketOptimizeIn,
        user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """当前时点（或指定区间末端）的 6 方法目标权重。

        严格回看窗口：未指定 `start` 时，要求清洗行情至少有 `lookback_days`
        个交易日；不足返回 400（回测端点则允许成分逐步纳入，不做此严格校验）。
        """
        _validate_method(payload.method)
        pairs = _pairs(payload)
        keys = _keys(pairs)
        _validate_risk_budget(payload, keys)

        with db.get_conn() as conn:
            panel = _load_panel(conn, pairs)
        panel = _slice_panel(panel, payload.end)
        if panel.empty:
            raise HTTPException(400, "所选区间无清洗行情数据")

        returns = _returns_from_panel(panel)
        if payload.start is not None:
            returns = returns.loc[payload.start:]
        if returns.empty:
            raise HTTPException(400, "所选区间无有效收益样本")
        if payload.start is None and len(returns) < payload.lookback_days:
            raise HTTPException(
                400,
                f"回看窗口不足：可用 {len(returns)} 个交易日，"
                f"需 {payload.lookback_days} 个",
            )

        window = returns.tail(payload.lookback_days)
        if len(window) < 2:
            raise HTTPException(400, f"回看窗口不足：仅 {len(window)} 个交易日")

        try:
            weights = optimize(
                window,
                payload.method,
                lookback=len(window),
                risk_free=payload.risk_free,
                risk_budget=payload.risk_budget,
                trading_days=trading_days,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        diagnostics = summarize_returns(
            window, weights, risk_free=payload.risk_free, trading_days=trading_days
        )

        body = {
            "method": payload.method,
            "weights": _weight_rows(pairs, keys, weights),
            "diagnostics": {
                "method": payload.method,
                "lookback": payload.lookback_days,
                "effective_start": (
                    _iso_date(window.index[0]) if len(window) > 0 else None
                ),
                "n_obs": int(diagnostics["n_obs"]),
                "volatility": float(diagnostics["annualized_vol"]),
                "sharpe": float(diagnostics["sharpe"]),
                "annualized_return": float(diagnostics["annualized_return"]),
                "active_assets": int((np.asarray(weights) > 0).sum()),
            },
        }
        return _json_safe(body)

    @app.post("/api/basket/backtest")
    def basket_backtest(
        payload: BasketBacktestIn,
        user: auth.UserContext | None = Depends(auth.optional_user),
    ) -> dict:
        """篮子模式逐日回测：净值曲线 + 年化/波动/回撤 + 换手率 + 逐资产贡献。

        再平衡语义与 `quant/backtest.py` 一致：任一资产漂移偏离目标
        > `rebalance_band`（绝对值）→ 整体回到当日最优目标。
        成分逐步纳入：不足窗口的资产权重为 0，不拖后整体 effective_start。
        """
        _validate_method(payload.method)
        pairs = _pairs(payload)
        keys = _keys(pairs)
        _validate_risk_budget(payload, keys)

        with db.get_conn() as conn:
            panel = _load_panel(conn, pairs)
        panel = _slice_panel(panel, payload.end)
        if panel.empty:
            raise HTTPException(400, "所选区间无清洗行情数据")

        try:
            result = run_basket_backtest(
                panel,
                method=payload.method,
                lookback=payload.lookback_days,
                min_window=min(default_min_window, payload.lookback_days),
                rebalance_band=payload.rebalance_band,
                risk_free=payload.risk_free,
                risk_budget=payload.risk_budget,
                trading_days=trading_days,
                fee_rate=payload.fee_rate,
                slippage_rate=payload.slippage_rate,
                stamp_duty_rate=payload.stamp_duty_rate,
                user_start=payload.start,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        contributions = []
        for item in result.asset_contributions:
            symbol, source = _split_key(str(item.get("key", "")))
            contributions.append(
                {
                    "key": item.get("key"),
                    "symbol": symbol,
                    "source": source,
                    "avg_weight": float(item.get("avg_weight", 0.0)),
                    "asset_return": float(item.get("asset_return", 0.0)),
                    "contribution": float(item.get("contribution", 0.0)),
                }
            )

        nav_rows = [
            {
                "trade_date": _iso_date(index),
                "nav": float(row["nav"]),
                "ret": float(row["ret"]),
            }
            for index, row in result.nav.iterrows()
        ]

        rebalance_rows = [
            {**rb, "trade_date": _iso_date(rb["trade_date"])}
            for rb in result.rebalances
        ]

        weight_rows = _weight_rows(
            pairs, keys, np.array([result.latest_target.get(k, 0.0) for k in keys])
        )

        eq_nav_rows = [
            {"trade_date": _iso_date(index), "nav": float(value)}
            for index, value in result.equal_weight_nav.items()
        ]

        rebalance_events = []
        for rb in result.rebalances:
            prev = rb.get("prev_weights") or {}
            target_weights = rb.get("target_weights") or {}
            event_assets = []
            for key in sorted(set(prev) | set(target_weights)):
                symbol, source = _split_key(str(key))
                before = float(prev.get(key, 0.0))
                after = float(target_weights.get(key, 0.0))
                event_assets.append(
                    {
                        "key": key,
                        "symbol": symbol,
                        "source": source,
                        "prev_weight": before,
                        "target_weight": after,
                        "delta": after - before,
                    }
                )
            rebalance_events.append(
                {
                    "trade_date": _iso_date(rb["trade_date"]),
                    "reason": rb.get("reason"),
                    "turnover": float(rb.get("turnover") or 0.0),
                    "max_deviation": float(rb.get("max_deviation") or 0.0),
                    "assets": event_assets,
                }
            )

        body = {
            "method": payload.method,
            "effective_start": _iso_date(result.effective_start),
            "lookback": payload.lookback_days,
            "n_obs": int(result.n_obs),
            "nav": nav_rows,
            "equal_weight_nav": eq_nav_rows,
            "equal_weight_metrics": result.equal_weight_metrics,
            "rebalance_events": rebalance_events,
            "annualized_return": float(result.metrics["annualized_return"]),
            "annualized_vol": float(result.metrics["annualized_vol"]),
            "max_drawdown": float(result.metrics["max_drawdown"]),
            "sharpe": float(result.metrics["sharpe"]),
            "sortino": float(result.metrics["sortino"]),
            "calmar": float(result.metrics["calmar"]),
            "trading_days": int(trading_days),
            "turnover": float(result.annualized_turnover),
            "turnover_total": float(result.total_turnover),
            "rebalance_count": len(result.rebalances),
            "fees": dict(result.fees),
            "weights": weight_rows,
            "contributions": contributions,
            "rebalances": rebalance_rows,
            "metrics": result.metrics,
        }
        return _json_safe(body)
