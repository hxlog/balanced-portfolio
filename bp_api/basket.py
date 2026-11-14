"""一篮子资产风险平价 — API 端点（register_routes 模式）。

两个只读计算端点（不落库、不触发任务）：
  POST /api/basket/optimize   给定资产池 → 6 方法之一的当前目标权重 + 诊断
  POST /api/basket/backtest   同一资产池 + 再平衡漂移带 → 净值曲线/年化/回撤/换手/贡献

数据只读 `bp_quote_clean`（经 `repositories.load_price_panel` 构建价格面板），
鉴权与估值接口一致：`Depends(auth.optional_user)`，匿名可调用。
main.py 的路由注册由主控完成，本模块只提供 `register_routes(app)`。
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException

from . import auth, db, repositories as repo
from .quant.basket import METHODS, optimize, run_basket_backtest, summarize_returns
from .repositories import _json_safe
from .schemas import BasketBacktestIn, BasketOptimizeIn
from .settings import load_settings

logger = logging.getLogger(__name__)


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
                    str(window.index[0]) if len(window) > 0 else None
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
                "trade_date": str(index),
                "nav": float(row["nav"]),
                "ret": float(row["ret"]),
            }
            for index, row in result.nav.iterrows()
        ]

        weight_rows = _weight_rows(
            pairs, keys, np.array([result.latest_target.get(k, 0.0) for k in keys])
        )

        body = {
            "method": payload.method,
            "effective_start": str(result.effective_start),
            "lookback": payload.lookback_days,
            "n_obs": int(result.n_obs),
            "nav": nav_rows,
            "annualized_return": float(result.metrics["annualized_return"]),
            "annualized_vol": float(result.metrics["annualized_vol"]),
            "max_drawdown": float(result.metrics["max_drawdown"]),
            "sharpe": float(result.metrics["sharpe"]),
            "turnover": float(result.annualized_turnover),
            "turnover_total": float(result.total_turnover),
            "rebalance_count": len(result.rebalances),
            "weights": weight_rows,
            "contributions": contributions,
            "rebalances": result.rebalances,
            "metrics": result.metrics,
        }
        return _json_safe(body)
