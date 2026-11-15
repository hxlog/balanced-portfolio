# -*- coding: utf-8 -*-
"""MVI 市场估值指数研究脚本。

目标：用 5 大宽基周频估值因子（PE/PB 分位反向、股息率/ERP/ROE 分位正向）
合成 0-100 的市场估值指数（0=极度低估，100=极度高估），使「低估值买入后未来
1 年收益」的 Spearman IC 最大。

三种模型对比：
A. 约束线性加权 + Spearman IC 最大化（SLSQP，权重>=0 且和为 1）
B. PCA(2) + 岭回归（共线性处理）
C. 梯度提升树（numpy 手写 depth-2 boosting，仅作对比基准）

walk-forward：训练 ≤ T，测试 T..T+1年（前向 252 交易日标签）。
输出：docs/index-valuation/21-mvi-research-report.md + 权重 JSON。
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import spearmanr

sys.path.insert(0, "/opt/balanced-portfolio")
sys.path.insert(0, "/opt/balanced-portfolio/bp_ingest")
sys.stdout.reconfigure(encoding="utf-8")

from bp_ingest.config import load_config
from bp_ingest.db import connect

PROXIES = ["000016", "000300", "000510", "000905", "000852"]
FACTORS = ["cheap_pe", "cheap_pb", "div_pct", "erp_pct", "roe_pct"]
FACTOR_LABELS = {
    "cheap_pe": "PE 分位（反向）",
    "cheap_pb": "PB 分位（反向）",
    "div_pct": "股息率分位",
    "erp_pct": "风险溢价分位",
    "roe_pct": "ROE 分位",
}
ROLL_WEEKS = 104   # 3 年滚动分位
MIN_WEEKS = 26
FWD_DAYS = 252


def rolling_percentile(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    def pct_rank(values: np.ndarray) -> float:
        current = values[-1]
        return float((values <= current).sum()) / len(values) * 100.0

    return series.rolling(window, min_periods=min_periods).apply(pct_rank, raw=True)


def load_panel(conn) -> pd.DataFrame:
    """5 大宽基的周频估值面板 → 滚动分位因子（跨宽基等权平均）。"""
    factor_frames: dict[str, list[pd.Series]] = {f: [] for f in FACTORS}
    for code in PROXIES:
        query = """
            SELECT trade_date, metric, value
            FROM bp_index_valuation_series
            WHERE index_code = %s AND trade_date >= DATE '2015-01-01'
              AND metric IN ('pe_ttm', 'pb', 'dividend_yield_ttm', 'erp')
        """
        df = pd.read_sql(query, conn, params=(code,))
        if df.empty:
            continue
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        wide = df.pivot_table(index="trade_date", columns="metric", values="value", aggfunc="last").sort_index()
        wide = wide.apply(pd.to_numeric, errors="coerce")
        if "pe_ttm" not in wide or "pb" not in wide:
            continue
        wide = wide[wide["pe_ttm"].notna() & wide["pb"].notna()]
        wide["roe_ttm"] = wide["pb"] / wide["pe_ttm"] * 100.0
        for factor, col, invert in [
            ("cheap_pe", "pe_ttm", True), ("cheap_pb", "pb", True),
            ("div_pct", "dividend_yield_ttm", False), ("erp_pct", "erp", False),
            ("roe_pct", "roe_ttm", False),
        ]:
            series = wide[col].astype(float)
            pct = rolling_percentile(series, ROLL_WEEKS, MIN_WEEKS)
            if invert:
                pct = 100.0 - pct
            factor_frames[factor].append(pct.rename("p"))
    combined = {}
    for factor, frames in factor_frames.items():
        if not frames:
            continue
        combined[factor] = pd.concat(frames, axis=1).mean(axis=1, skipna=True)
    panel = pd.DataFrame(combined).sort_index()
    panel = panel.dropna(subset=["cheap_pe", "cheap_pb"])
    return panel


def load_forward_return(conn) -> pd.Series:
    """沪深300 未来 252 交易日收益（bfq 收盘）。"""
    query = """
        SELECT trade_date, close FROM bp_index_quote_daily
        WHERE symbol = '000300' AND adjust = 'bfq' ORDER BY trade_date
    """
    df = pd.read_sql(query, conn)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.drop_duplicates(subset=["trade_date"], keep="last")
    df = df.set_index("trade_date").sort_index()
    close = pd.to_numeric(df["close"], errors="coerce")
    fwd = close.shift(-FWD_DAYS) / close - 1.0
    return fwd


def walk_forward(panel: pd.DataFrame, fwd: pd.Series, train_end: str, test_end: str) -> dict:
    label = fwd.reindex(panel.index)
    train = panel.loc[:train_end].copy()
    train_label = label.loc[:train_end]
    valid = train_label.notna()
    train, train_label = train[valid], train_label[valid]
    test_idx = (panel.index > pd.Timestamp(train_end)) & (panel.index <= pd.Timestamp(test_end))
    test = panel[test_idx]
    test_label = label[test_idx]
    test_valid = test_label.notna()
    test, test_label = test[test_valid], test_label[test_valid]
    train = train.dropna()
    train_label = train_label.reindex(train.index)
    test = test.dropna()
    test_label = test_label.reindex(test.index)
    if len(train) < 60 or len(test) < 12:
        return {"ok": False, "reason": "样本不足", "train": len(train), "test": len(test)}

    # A. 约束线性加权 + Spearman IC 最大化
    X_train = train[FACTORS].to_numpy(float)
    y_train = train_label.to_numpy(float)

    def neg_ic(w):
        score = X_train @ w
        return -float(spearmanr(score, y_train).correlation)

    best = None
    for seed in range(6):
        w0 = np.array([0.2, 0.2, 0.2, 0.2, 0.2]) + np.random.default_rng(seed).normal(0, 0.05, 5)
        w0 = np.clip(w0, 0.01, None); w0 = w0 / w0.sum()
        res = minimize(neg_ic, w0, method="SLSQP",
                       bounds=[(0.0, 1.0)] * 5,
                       constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                       options={"maxiter": 300, "ftol": 1e-8})
        if res.success and (best is None or res.fun < best.fun):
            best = res
    w_lin = best.x if best is not None else np.full(5, 0.2)
    model_a = {"weights": dict(zip(FACTORS, map(float, w_lin)))}

    X_test = test[FACTORS].to_numpy(float)
    y_test = test_label.to_numpy(float)
    ic_a = float(spearmanr(X_test @ w_lin, y_test).correlation)

    # B. PCA(2) + 岭回归
    mean = X_train.mean(axis=0)
    std = X_train.std(axis=0) + 1e-9
    Z = (X_train - mean) / std
    U, S, Vt = np.linalg.svd(Z, full_matrices=False)
    k = 2
    P = Vt[:k]
    z_test = (X_test - mean) / std
    # 在训练集上做 5 折时间序列岭回归选择 lambda
    def ridge_fit(Ztr, ytr, lam):
        beta = np.linalg.solve(Ztr.T @ Ztr + lam * np.eye(Ztr.shape[1]), Ztr.T @ ytr)
        return beta
    best_b = None
    for lam in (0.1, 1.0, 10.0, 100.0):
        scores = []
        for cut in (0.6, 0.7, 0.8, 0.9):
            idx = int(len(Z) * cut)
            beta = ridge_fit(Z[:idx] @ P.T, y_train[:idx], lam)
            pred = Z[idx:] @ P.T @ beta
            scores.append(abs(float(spearmanr(pred, y_train[idx:]).correlation)))
        avg = float(np.mean(scores))
        if best_b is None or avg > best_b[1]:
            best_b = (lam, avg)
    beta = ridge_fit(Z @ P.T, y_train, best_b[0])
    # 回写因子权重（标准化空间）
    w_pca_raw = P.T @ beta
    w_pca = np.zeros(5)
    # 仅保留非负权重方向；若回归方向与预期相反则截断为 0
    w_pca = np.clip(w_pca_raw, 0.0, None)
    if w_pca.sum() <= 0:
        w_pca = np.full(5, 0.2)
    w_pca = w_pca / w_pca.sum()
    ic_b = float(spearmanr(z_test @ P.T @ beta, y_test).correlation) if test_valid.sum() else float("nan")
    ic_b = abs(ic_b)

    # C. 梯度提升树（numpy depth-2 树桩提升，回归未来收益）
    class Stump:
        def __init__(self, feat, thr, left, right):
            self.feat, self.thr, self.left, self.right = feat, thr, left, right

        def predict(self, X):
            return np.where(X[:, self.feat] <= self.thr, self.left, self.right)

    def fit_gbdt(X, y, n_rounds=30, lr=0.1):
        base = float(np.median(y))
        pred = np.full(len(y), base)
        trees = []
        for _ in range(n_rounds):
            resid = y - pred
            best = None
            for feat in range(X.shape[1]):
                thrs = np.quantile(X[:, feat], [0.2, 0.4, 0.6, 0.8])
                for thr in thrs:
                    left = resid[X[:, feat] <= thr]
                    right = resid[X[:, feat] > thr]
                    if len(left) < 5 or len(right) < 5:
                        continue
                    loss = ((left - left.mean()) ** 2).sum() + ((right - right.mean()) ** 2).sum()
                    if best is None or loss < best[0]:
                        best = (loss, feat, float(thr), float(left.mean()), float(right.mean()))
            if best is None:
                break
            _, feat, thr, ml, mr = best
            tree = Stump(feat, thr, ml, mr)
            pred += lr * tree.predict(X)
            trees.append(tree)
        return {"base": base, "trees": trees, "lr": lr}

    def pred_gbdt(model, X):
        out = np.full(len(X), model["base"])
        for tree in model["trees"]:
            out += model["lr"] * tree.predict(X)
        return out

    gbdt = fit_gbdt(Z, y_train)
    ic_c = abs(float(spearmanr(pred_gbdt(gbdt, (X_test - mean) / std), y_test).correlation))

    return {
        "ok": True,
        "train": int(len(train)), "test": int(len(test)),
        "train_start": str(train.index.min().date()), "train_end": str(train.index.max().date()),
        "test_start": str(test.index.min().date()), "test_end": str(test.index.max().date()),
        "ic_a": ic_a, "ic_b": ic_b, "ic_c": ic_c,
        "weights_a": {k: round(float(v), 4) for k, v in zip(FACTORS, w_lin)},
        "weights_b": {k: round(float(v), 4) for k, v in zip(FACTORS, w_pca)},
        "lambda_b": best_b[0],
    }


def latest_score(panel: pd.DataFrame, fwd: pd.Series, fallback_w=None):
    label = fwd.reindex(panel.index)
    X = panel[FACTORS].to_numpy(float)
    y = label.to_numpy(float)
    mask = ~np.isnan(y)
    X, y = X[mask], y[mask]
    def neg_ic(w):
        return -float(spearmanr(X @ w, y).correlation)
    best = None
    for seed in range(12):
        w0 = np.full(5, 0.2) + np.random.default_rng(seed).normal(0, 0.06, 5)
        w0 = np.clip(w0, 0.01, None); w0 = w0 / w0.sum()
        res = minimize(neg_ic, w0, method="SLSQP", bounds=[(0, 1)] * 5,
                       constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                       options={"maxiter": 300, "ftol": 1e-8})
        if res.success and (best is None or res.fun < best.fun):
            best = res
    w = best.x if best is not None else (np.asarray(fallback_w) if fallback_w is not None else np.full(5, 0.2))
    # 用滚动 3 年标准化后加权（百分位本身 0-100）
    latest = panel.iloc[-1]
    cheap = float(sum(w[i] * float(latest[FACTORS[i]]) for i in range(5)))
    mvi = 100.0 - cheap
    contributions = {FACTOR_LABELS[f]: round(float(w[i] * latest[f]), 2) for i, f in enumerate(FACTORS)}
    return {
        "as_of": str(panel.index[-1].date()),
        "mvi": round(mvi, 2),
        "cheap_score": round(cheap, 2),
        "zone": ("极度低估" if mvi < 20 else "低估" if mvi < 40 else "合理" if mvi < 60 else "高估" if mvi < 80 else "极度高估"),
        "weights": {FACTOR_LABELS[f]: round(float(w[i]), 4) for i, f in enumerate(FACTORS)},
        "factor_values": {FACTOR_LABELS[f]: round(float(latest[f]), 1) for f in FACTORS},
        "contributions": contributions,
    }


def main() -> int:
    cfg = load_config()
    with connect(cfg.db) as conn:
        panel = load_panel(conn)
        fwd = load_forward_return(conn)
    print("panel:", panel.shape, "range:", panel.index.min().date(), "->", panel.index.max().date())
    folds = []
    for train_end, test_end in [("2023-11-14", "2024-11-14"), ("2024-11-14", "2025-11-14")]:
        fold = walk_forward(panel, fwd, train_end, test_end)
        fold["fold"] = train_end + " -> " + test_end
        folds.append(fold)
        print(json.dumps(fold, ensure_ascii=False, indent=1))
    last_ok = [f for f in folds if f.get('ok')]
    fallback = None
    if last_ok:
        fb = last_ok[-1].get('weights_a') or {}
        fallback = [float(fb.get(k, 0.2)) for k in FACTORS]
    latest = latest_score(panel, fwd, fallback)
    print("latest:", json.dumps(latest, ensure_ascii=False))
    result = {"proxies": PROXIES, "factors": FACTORS, "folds": folds, "latest": latest,
              "data_range": [str(panel.index.min().date()), str(panel.index.max().date())],
              "n_obs": int(len(panel))}
    out_dir = "/opt/balanced-portfolio/docs/index-valuation"
    os.makedirs(out_dir, exist_ok=True)
    with open(out_dir + "/mvi-research.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("saved mvi-research.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
