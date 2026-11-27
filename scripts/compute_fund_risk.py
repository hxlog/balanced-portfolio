# -*- coding: utf-8 -*-
"""计算基金风险指标（净值口径修复版）→ bp_fund_risk。

背景与口径（2026-11-27 修复）
------------------------------
旧版脚本直接用 bp_fund_nav_daily.nav（单位净值）计算收益率，忽略分红/份额拆分：
以 SH513660（华夏沪港通恒生ETF）为例，2026-04-20 单位净值因份额折算单日 -49.63%，
旧版 vs HSI 的 1 年跟踪误差被抬高到 50.57%；改用累计净值后约 4.3%。

本脚本口径（详见 docs/fund-risk.md）：
1. 净值主口径 = bp_fund_nav_daily.acc_nav（累计净值，含分红再投）。
   acc_nav 覆盖不足（小于 MIN_OBS 个观测）时回退 bp_etf_quote_daily 的 hfq 后复权：
   基金代码去掉 SH/SZ/OF 前缀归一为 etf_code，按交易日对齐（同一只 ETF 多源时
   优先取覆盖最长的 hfq 源，不混用不同来源的绝对价）。两者都没有时才退回单位净值
   nav（最后兜底，会标注 basis=nav）。
2. 基准 = 基金主跟踪指数（按最新交易日 AUM 最大）。HSI 优先用全收益序列
   （若库内存在 HSI_TR 类免费源序列）；实际库内没有全收益指数，故用
   HSI 价格指数 × HKDCNY（人民币计价基金 vs 港币计价指数，必须做汇率调整），
   口径写入 --report 输出与 docs/fund-risk.md。
3. 断点检测：单日 |收益| > 30% 视为断点。
   - 单日尖刺后次日反向抵消 -> 剔除异常点（spike_removed）；
   - 其余（份额拆分/折算造成的水平跳变）-> 断点因子对断点前段缩放，使序列连续
     （断点当日收益约 0，断点前各段内部收益不变）（level_shift）；
   - 交叉记录「单位净值拆分但累计净值连续」事件（nav_split_ignored，改用 acc_nav
     后无需修正）。
   事件明细写 --report JSON；stdout 只打印汇总。
4. 结果写 bp_fund_risk（as_of = 净值最后一日、updated_at = now()），幂等 upsert。

用法
----
    python scripts/compute_fund_risk.py                     # 全量重算（跟踪基金全集）
    python scripts/compute_fund_risk.py --fund SH513660     # 单只调试（打印指标）
    python scripts/compute_fund_risk.py --dry-run --report /tmp/fund_risk.json
    python scripts/compute_fund_risk.py --hsi-basis price   # 复现 4.31%（不含汇率调整）

测试：python -m pytest bp_api/tests/test_fund_risk.py -q
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

# 允许直接运行脚本时从仓库根目录导入 bp_ingest。
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bp_ingest.config import load_config  # noqa: E402
from bp_ingest.db import connect  # noqa: E402

try:  # 服务器以重定向 stdout 运行时 reconfigure 可能不可用（pytest capture 等）
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

TRADING_DAYS = 252
TE_WINDOW = 252
MIN_OBS = 60
BREAK_THRESHOLD = 0.30
# 尖刺判定：断点当日与次日收益的对数比之和足够接近 0（约 +/-17% 内），视为一次性坏点
SPIKE_LOG_TOLERANCE = 0.15

HSI_CODE = "HSI"
# 若未来接入「恒生指数全收益」免费源，把库内 symbol 放在这里即可自动优先使用
HSI_TOTAL_RETURN_CANDIDATES = ("HSI_TR", "HSITR", "HSI-TR", "HSI全收益")
# 港币计价指数 -> 人民币汇率对：人民币计价基金必须按汇率调整后的指数做基准
BENCHMARK_FX_PAIRS = {HSI_CODE: "HKDCNY"}

# 场内 ETF 后复权多源时的优先级（覆盖最长且口径一致的腾讯 hfq 优先），未列出的按行数降序
ETF_HFQ_SOURCE_PRIORITY = (
    "tencent_etf_kline",
    "em_kline:anchored",
    "sina_etf_kline",
    "tencent_kline",
    "sina_etf_kline:factor",
)

NAV_BASIS_ACC = "acc_nav"
NAV_BASIS_ETF = "etf_hfq"
NAV_BASIS_NAV = "nav"
BENCHMARK_BASIS_HSI_TR = "hsi_total_return"
BENCHMARK_BASIS_HSI_FX = "hsi_price_x_hkdcny"
BENCHMARK_BASIS_PRICE = "price"

HSI_BASIS_CHOICES = ("auto", "hsi_total_return", "price_x_hkdcny", "price")

_PREFIX_RE = re.compile(r"^(SH|SZ|OF)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def normalize_etf_code(fund_code: str) -> str:
    """基金代码 -> 场内 ETF 代码（SH513660/SZ159920/OF000001 -> 513660/159920/000001）。"""
    return _PREFIX_RE.sub("", str(fund_code or "").strip())


def _positive_series(values: pd.Series) -> pd.Series:
    """去空、转 float、丢弃非正值、按日期排序。"""
    s = pd.to_numeric(values, errors="coerce").dropna()
    s = s[s > 0]
    return s.sort_index()


@dataclass
class BreakEvent:
    trade_date: date
    kind: str  # level_shift / spike_removed / nav_split_ignored
    factor: float
    raw_return: float

    def as_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat(),
            "kind": self.kind,
            "factor": round(float(self.factor), 8),
            "raw_return": round(float(self.raw_return), 8),
        }


def _index_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def detect_and_repair_breaks(
    series: pd.Series, threshold: float = BREAK_THRESHOLD
) -> tuple[pd.Series, list[BreakEvent]]:
    """检测并修复净值序列的单日断点（|收益| > threshold）。

    修复策略：
    - 尖刺：断点当日与次日方向相反、对数收益近似抵消 -> 丢弃断点当日（坏点）；
    - 水平跳变：其余情形（份额拆分/折算/数据重定基）-> 断点因子缩放断点前段，
      使整条序列连续；断点前各段内部收益不变，断点当日收益约 0。
    返回 (修复后序列, 事件列表)。
    """
    s = series.sort_index().dropna()
    if len(s) < 3:
        return s, []
    vals = s.to_numpy(dtype=float)
    idx = list(s.index)
    rets = np.full(len(vals), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        rets[1:] = vals[1:] / vals[:-1] - 1.0

    drop = np.zeros(len(vals), dtype=bool)
    level_shifts: list[tuple[int, float]] = []
    events: list[BreakEvent] = []
    skip: set[int] = set()
    for i in range(1, len(vals)):
        if i in skip:
            continue
        r = rets[i]
        if not np.isfinite(r) or abs(r) <= threshold:
            continue
        if i + 1 < len(vals):
            r_next = vals[i + 1] / vals[i] - 1.0
            if (
                np.isfinite(r_next)
                and abs(r_next) > threshold
                and abs(math.log1p(r) + math.log1p(r_next)) <= SPIKE_LOG_TOLERANCE
            ):
                drop[i] = True
                skip.add(i + 1)
                events.append(BreakEvent(_index_date(idx[i]), "spike_removed", 1.0, float(r)))
                continue
        factor = float(vals[i] / vals[i - 1])
        if not math.isfinite(factor) or factor <= 0:
            drop[i] = True
            events.append(BreakEvent(_index_date(idx[i]), "spike_removed", 1.0, float(r)))
            continue
        level_shifts.append((i, factor))
        events.append(BreakEvent(_index_date(idx[i]), "level_shift", factor, float(r)))

    if not level_shifts and not drop.any():
        return s, []
    adjusted = vals.copy()
    for i, factor in level_shifts:  # 升序；乘法可交换
        adjusted[:i] = adjusted[:i] * factor
    keep_idx = [d for d, keep in zip(idx, ~drop) if keep]
    out = pd.Series(adjusted[~drop], index=keep_idx, dtype=float)
    return out.sort_index(), events


def detect_nav_splits(
    nav: pd.Series, acc: pd.Series, threshold: float = BREAK_THRESHOLD
) -> list[BreakEvent]:
    """交叉检测：单位净值单日跳变超过阈值、但同日期累计净值连续 -> 拆分/折算事件。

    这类事件在改用 acc_nav 后无需修正，仅记录，用于审计旧 nav 口径为什么会产生巨幅 TE。
    """
    if nav.empty or acc.empty:
        return []
    frame = pd.concat([nav.rename("nav"), acc.rename("acc")], axis=1, join="inner").sort_index()
    if len(frame) < 3:
        return []
    nav_vals = frame["nav"].to_numpy(dtype=float)
    acc_vals = frame["acc"].to_numpy(dtype=float)
    dates = list(frame.index)
    events: list[BreakEvent] = []
    for i in range(1, len(nav_vals)):
        if nav_vals[i - 1] <= 0 or acc_vals[i - 1] <= 0:
            continue
        r_nav = nav_vals[i] / nav_vals[i - 1] - 1.0
        r_acc = acc_vals[i] / acc_vals[i - 1] - 1.0
        if abs(r_nav) <= threshold or abs(r_acc) > threshold:
            continue
        events.append(
            BreakEvent(_index_date(dates[i]), "nav_split_ignored", float(1.0 + r_nav), float(r_nav))
        )
    return events


# ---------------------------------------------------------------------------
# 单只基金净值序列选择
# ---------------------------------------------------------------------------
@dataclass
class FundSeries:
    series: pd.Series
    basis: str
    repair_events: list[BreakEvent] = field(default_factory=list)
    cross_check_events: list[BreakEvent] = field(default_factory=list)


def pick_fund_series(
    nav: pd.Series,
    acc: pd.Series,
    etf: Optional[pd.Series],
    *,
    min_obs: int = MIN_OBS,
) -> Optional[FundSeries]:
    """按 acc_nav -> ETF hfq -> nav 的优先级选出用于指标计算的净值价序列。"""
    nav = _positive_series(nav)
    acc = _positive_series(acc)
    etf = _positive_series(etf) if etf is not None and not etf.empty else None

    if len(acc) >= min_obs and (not len(nav) or len(acc) >= 0.9 * len(nav)):
        chosen, basis = acc, NAV_BASIS_ACC
    elif etf is not None and len(etf) >= min_obs:
        chosen, basis = etf, NAV_BASIS_ETF
    elif len(acc) >= min_obs:
        chosen, basis = acc, NAV_BASIS_ACC
    elif len(nav) >= min_obs:
        chosen, basis = nav, NAV_BASIS_NAV
    else:
        return None

    repaired, repair_events = detect_and_repair_breaks(chosen)
    cross_check = detect_nav_splits(nav, acc) if basis != NAV_BASIS_NAV and len(acc) else []
    return FundSeries(
        series=repaired,
        basis=basis,
        repair_events=repair_events,
        cross_check_events=cross_check,
    )


# ---------------------------------------------------------------------------
# 指标计算（沿用旧版口径，只把输入换成修复后的复权净值序列）
# ---------------------------------------------------------------------------
def compute_fund_metrics(nav: pd.Series, index_ret: Optional[pd.Series]) -> Optional[dict]:
    """年化收益/波动/回撤/YTD/TE/IR；样本不足 60 返回 None。

    口径与旧版一致：1y 为区间总收益，3y/5y 为年化；TE 取最近 252 个对齐日收益差的
    标准差 x sqrt(252)（百分数点）。
    """
    nav = _positive_series(nav)
    if len(nav) < MIN_OBS:
        return None
    last = nav.index[-1]
    out: dict[str, Any] = {"as_of": _index_date(last), "n_obs": int(len(nav))}
    year_start = date(last.year - 1, 12, 31)
    date_idx = [_index_date(d) for d in nav.index]
    prior = nav[[d <= year_start for d in date_idx]]
    out["ytd"] = (
        round(float(nav.iloc[-1] / prior.iloc[-1] - 1) * 100, 4) if len(prior) else None
    )
    for label, days, annualize in (
        ("1y", TRADING_DAYS, False),
        ("3y", TRADING_DAYS * 3, True),
        ("5y", TRADING_DAYS * 5, True),
    ):
        if len(nav) <= days:
            out["ret_" + label] = None
            continue
        total = float(nav.iloc[-1] / nav.iloc[-days - 1])
        years = days / TRADING_DAYS
        out["ret_" + label] = round(
            ((total ** (1 / years) - 1) if annualize else (total - 1)) * 100, 4
        )
    window = nav.iloc[-TRADING_DAYS:] if len(nav) > TRADING_DAYS else nav
    rets = window.pct_change().dropna()
    out["ann_vol_1y"] = (
        round(float(rets.std() * np.sqrt(TRADING_DAYS)) * 100, 4) if len(rets) > 10 else None
    )
    cummax = window.cummax()
    out["max_dd_1y"] = round(float((window / cummax - 1).min()) * 100, 4)

    if index_ret is not None and len(index_ret) > MIN_OBS:
        fund_ret = nav.pct_change().dropna()
        joined = pd.concat(
            [fund_ret.rename("fund"), index_ret.rename("bench")], axis=1, sort=False
        ).dropna()
        tail = joined.iloc[-TE_WINDOW:]
        if len(tail) > MIN_OBS:
            diff = tail["fund"] - tail["bench"]
            te = float(diff.std() * np.sqrt(TRADING_DAYS))
            out["tracking_error_1y"] = round(te * 100, 4)
            bench_ann = (
                float((1 + tail["bench"]).prod()) ** (TRADING_DAYS / len(tail)) - 1
                if len(tail)
                else None
            )
            if te > 1e-9 and out.get("ret_1y") is not None and bench_ann is not None:
                out["info_ratio_1y"] = round((out["ret_1y"] / 100 - bench_ann) / te, 4)
            else:
                out["info_ratio_1y"] = None
        else:
            out["tracking_error_1y"] = None
            out["info_ratio_1y"] = None
    else:
        out["tracking_error_1y"] = None
        out["info_ratio_1y"] = None
    return out


# ---------------------------------------------------------------------------
# 基准收益
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Benchmark:
    code: str
    returns: pd.Series
    basis: str


def apply_fx(price_ret: pd.Series, fx_ret: pd.Series) -> pd.Series:
    """价格指数收益 x 汇率收益（人民币计价基金 vs 港币/外币计价指数）。

    汇率按指数交易日 reindex + ffill（只用过去汇率，不引入未来数据）。
    """
    if price_ret is None or price_ret.empty:
        return pd.Series(dtype=float)
    aligned = fx_ret.reindex(price_ret.index).ffill().fillna(0.0)
    return (1.0 + price_ret) * (1.0 + aligned) - 1.0


def combine_benchmark_returns(
    price_ret: pd.Series,
    *,
    fx_ret: Optional[pd.Series] = None,
    has_total_return: bool = False,
    hsi_mode: str = "auto",
) -> tuple[pd.Series, str]:
    """按口径开关组合基准收益：全收益 -> 价格 x 汇率 -> 纯价格。"""
    if hsi_mode == "price":
        return price_ret, BENCHMARK_BASIS_PRICE
    if has_total_return and hsi_mode in ("auto", "hsi_total_return"):
        return price_ret, BENCHMARK_BASIS_HSI_TR
    if (
        hsi_mode in ("auto", "price_x_hkdcny", "hsi_total_return")
        and fx_ret is not None
        and not fx_ret.empty
    ):
        return apply_fx(price_ret, fx_ret), BENCHMARK_BASIS_HSI_FX
    return price_ret, BENCHMARK_BASIS_PRICE


_BENCHMARK_PRICE_SQL = """
WITH ranked AS (
    SELECT symbol, source,
           row_number() OVER (
               PARTITION BY symbol
               ORDER BY count(*) DESC, source
           ) AS rn
    FROM bp_index_quote_daily
    WHERE symbol = ANY(%s) AND adjust = 'bfq' AND close IS NOT NULL
    GROUP BY symbol, source
)
SELECT q.symbol, q.trade_date, q.close
FROM bp_index_quote_daily q
JOIN ranked r ON r.symbol = q.symbol AND r.source = q.source AND r.rn = 1
WHERE q.adjust = 'bfq' AND q.close IS NOT NULL
ORDER BY q.symbol, q.trade_date
"""

_BENCHMARK_CHUNK = 100


def _frame_to_series(frame: pd.DataFrame, symbol: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    part = frame[frame["symbol"] == symbol]
    if part.empty:
        return pd.Series(dtype=float)
    ts = pd.DatetimeIndex(pd.to_datetime(part["trade_date"]))
    values = pd.to_numeric(part["close"], errors="coerce").to_numpy(dtype=float)
    series = pd.Series(values, index=ts, dtype=float).dropna().sort_index()
    return series[~series.index.duplicated(keep="last")]


def _to_return_series(values: pd.Series) -> pd.Series:
    if values is None or values.empty:
        return pd.Series(dtype=float)
    return values.sort_index().pct_change().dropna()


def load_benchmark_returns(
    conn, index_codes: Sequence[str], *, hsi_mode: str = "auto"
) -> dict[str, Benchmark]:
    """加载基准收益：每个指数取库内覆盖最长的 bfq 价格源；HSI 可叠加全收益/汇率口径。"""
    codes = sorted({str(c) for c in index_codes if c})
    if not codes:
        return {}
    price_frames: list[pd.DataFrame] = []
    for chunk in _chunks(codes, _BENCHMARK_CHUNK):
        with conn.cursor() as cur:
            cur.execute(_BENCHMARK_PRICE_SQL, (list(chunk),))
            rows = cur.fetchall()
        if rows:
            price_frames.append(pd.DataFrame(rows, columns=["symbol", "trade_date", "close"]))
    price_frame = (
        pd.concat(price_frames, ignore_index=True)
        if price_frames
        else pd.DataFrame(columns=["symbol", "trade_date", "close"])
    )

    tr_symbol: Optional[str] = None
    tr_frame = pd.DataFrame(columns=["symbol", "trade_date", "close"])
    if HSI_CODE in codes and hsi_mode != "price":
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol FROM bp_index_quote_daily"
                " WHERE symbol = ANY(%s) AND adjust = 'bfq'"
                " GROUP BY symbol HAVING count(*) > 100",
                (list(HSI_TOTAL_RETURN_CANDIDATES),),
            )
            found = {row[0] for row in cur.fetchall()}
        for candidate in HSI_TOTAL_RETURN_CANDIDATES:
            if candidate in found:
                tr_symbol = candidate
                break
        if tr_symbol:
            with conn.cursor() as cur:
                cur.execute(
                    _BENCHMARK_PRICE_SQL.replace("symbol = ANY(%s)", "symbol = %s"),
                    (tr_symbol,),
                )
                rows = cur.fetchall()
            if rows:
                tr_frame = pd.DataFrame(rows, columns=["symbol", "trade_date", "close"])

    fx_ret_map: dict[str, pd.Series] = {}
    fx_pairs = sorted({pair for code, pair in BENCHMARK_FX_PAIRS.items() if code in codes})
    if fx_pairs:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, trade_date, close FROM bp_index_quote_daily"
                " WHERE symbol = ANY(%s) AND source = 'fx_sina' AND adjust = 'bfq'"
                " AND close IS NOT NULL ORDER BY symbol, trade_date",
                (fx_pairs,),
            )
            fx_rows = cur.fetchall()
        fx_frame = pd.DataFrame(fx_rows, columns=["symbol", "trade_date", "close"]) if fx_rows else pd.DataFrame()
        for pair in fx_pairs:
            fx_series = _frame_to_series(fx_frame, pair)
            rets = _to_return_series(fx_series)
            if not rets.empty:
                fx_ret_map[pair] = rets

    out: dict[str, Benchmark] = {}
    for code in codes:
        price = _frame_to_series(price_frame, code)
        if price.empty:
            continue
        price_ret = _to_return_series(price)
        has_tr = bool(tr_symbol) and code == HSI_CODE
        if has_tr and hsi_mode in ("auto", "hsi_total_return"):
            tr_ret = _to_return_series(_frame_to_series(tr_frame, tr_symbol or ""))
            if not tr_ret.empty:
                out[code] = Benchmark(code=code, returns=tr_ret, basis=BENCHMARK_BASIS_HSI_TR)
                continue
        pair = BENCHMARK_FX_PAIRS.get(code)
        returns, basis = combine_benchmark_returns(
            price_ret, fx_ret=fx_ret_map.get(pair) if pair else None, hsi_mode=hsi_mode
        )
        out[code] = Benchmark(code=code, returns=returns, basis=basis)
    return out


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------
_PRIMARY_INDEX_SQL = """
WITH last_fund_date AS (
    SELECT fund_code, max(trade_date) AS d
    FROM bp_index_tracker_fund
    {fund_filter}
    GROUP BY fund_code
), agg AS (
    SELECT t.fund_code, t.index_code, sum(t.aum) AS aum_sum
    FROM bp_index_tracker_fund t
    JOIN last_fund_date f
      ON f.fund_code = t.fund_code AND t.trade_date = f.d
    GROUP BY t.fund_code, t.index_code
)
SELECT DISTINCT ON (fund_code) fund_code, index_code
FROM agg
ORDER BY fund_code, aum_sum DESC NULLS LAST, index_code
"""


def load_primary_index(conn, fund_codes: Optional[Sequence[str]] = None) -> dict[str, str]:
    """基金 -> 主跟踪指数：取该基金最新跟踪日 AUM 合计最大的指数。"""
    if fund_codes:
        sql = _PRIMARY_INDEX_SQL.format(fund_filter="WHERE fund_code = ANY(%s)")
        params: tuple = (list(fund_codes),)
    else:
        sql = _PRIMARY_INDEX_SQL.format(fund_filter="")
        params = ()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return {row[0]: row[1] for row in cur.fetchall()}


def load_fund_nav(conn, fund_codes: Sequence[str]) -> pd.DataFrame:
    if not fund_codes:
        return pd.DataFrame(columns=["fund_code", "trade_date", "nav", "acc_nav"])
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fund_code, trade_date, nav, acc_nav FROM bp_fund_nav_daily"
            " WHERE fund_code = ANY(%s) ORDER BY fund_code, trade_date",
            (list(fund_codes),),
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["fund_code", "trade_date", "nav", "acc_nav"])


def load_etf_hfq(conn, etf_codes: Sequence[str]) -> dict[str, pd.Series]:
    """ETF 后复权收盘价（key=6 位 etf_code）。

    多源时只取一个源（优先 ETF_HFQ_SOURCE_PRIORITY，否则覆盖最长），避免不同源的
    绝对价基数混用；同一日期多源时保留首选源。
    """
    codes = sorted({normalize_etf_code(c) for c in etf_codes if c})
    if not codes:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT etf_code, trade_date, close, source FROM bp_etf_quote_daily"
            " WHERE etf_code = ANY(%s) AND adjust = 'hfq' AND close IS NOT NULL"
            " ORDER BY etf_code, trade_date",
            (codes,),
        )
        rows = cur.fetchall()
    if not rows:
        return {}
    frame = pd.DataFrame(rows, columns=["etf_code", "trade_date", "close", "source"])
    out: dict[str, pd.Series] = {}
    priority = {src: i for i, src in enumerate(ETF_HFQ_SOURCE_PRIORITY)}
    for code, part in frame.groupby("etf_code"):
        counts = part["source"].value_counts()
        candidates = sorted(
            counts.index,
            key=lambda src: (priority.get(src, len(priority)), -int(counts[src]), str(src)),
        )
        chosen = part[part["source"] == candidates[0]]
        ts = pd.DatetimeIndex(pd.to_datetime(chosen["trade_date"]))
        values = pd.to_numeric(chosen["close"], errors="coerce").to_numpy(dtype=float)
        series = pd.Series(values, index=ts, dtype=float).dropna().sort_index()
        out[str(code)] = series[~series.index.duplicated(keep="last")]
    return out


# ---------------------------------------------------------------------------
# 批量计算 + 落库
# ---------------------------------------------------------------------------
def _need_etf_fallback(nav_part: pd.DataFrame) -> bool:
    """该基金累计净值覆盖不足、需要尝试 ETF 后复权回退。"""
    ts = pd.DatetimeIndex(pd.to_datetime(nav_part["trade_date"]))
    nav = _positive_series(pd.Series(pd.to_numeric(nav_part["nav"], errors="coerce").to_numpy(dtype=float), index=ts))
    acc = _positive_series(pd.Series(pd.to_numeric(nav_part["acc_nav"], errors="coerce").to_numpy(dtype=float), index=ts))
    if len(nav) < MIN_OBS:
        return True
    return len(acc) < MIN_OBS or len(acc) < 0.9 * len(nav)


def build_risk_rows(
    nav_rows: pd.DataFrame,
    etf_series: Optional[dict[str, pd.Series]],
    primary: dict[str, str],
    benchmarks: dict[str, Benchmark],
    *,
    min_obs: int = MIN_OBS,
) -> tuple[list[dict], dict]:
    """把一批基金净值 -> bp_fund_risk 行（纯计算，不访问数据库）。

    返回 (rows, stats)；stats 含 nav_basis / benchmark_basis 计数与断点事件明细。
    """
    rows: list[dict] = []
    stats: dict[str, Any] = {
        "funds": 0,
        "rows": 0,
        "nav_basis_counts": Counter(),
        "benchmark_basis_counts": Counter(),
        "repair_events": [],
        "nav_split_events": [],
        "skipped": [],
        "metrics": {},
    }
    if nav_rows is None or nav_rows.empty:
        return rows, stats
    frame = nav_rows.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    for fund_code, part in frame.groupby("fund_code", sort=True):
        benchmark_code = primary.get(fund_code)
        if not benchmark_code:
            stats["skipped"].append({"fund_code": fund_code, "reason": "no_primary_index"})
            continue
        part = part.sort_values("trade_date")
        index = pd.DatetimeIndex(pd.to_datetime(part["trade_date"]))
        nav = pd.Series(pd.to_numeric(part["nav"], errors="coerce").to_numpy(dtype=float), index=index)
        acc = pd.Series(pd.to_numeric(part["acc_nav"], errors="coerce").to_numpy(dtype=float), index=index)
        etf = etf_series.get(normalize_etf_code(fund_code)) if etf_series else None
        picked = pick_fund_series(nav, acc, etf, min_obs=min_obs)
        if picked is None:
            stats["skipped"].append({"fund_code": fund_code, "reason": "insufficient_history"})
            continue
        stats["funds"] += 1
        stats["nav_basis_counts"][picked.basis] += 1
        for event in picked.repair_events:
            stats["repair_events"].append({"fund_code": fund_code, **event.as_dict()})
        for event in picked.cross_check_events:
            stats["nav_split_events"].append({"fund_code": fund_code, **event.as_dict()})
        benchmark = benchmarks.get(benchmark_code)
        metrics = compute_fund_metrics(
            picked.series, benchmark.returns if benchmark is not None else None
        )
        if metrics is None:
            stats["skipped"].append({"fund_code": fund_code, "reason": "metrics_none"})
            continue
        rows.append(
            {
                "fund_code": fund_code,
                "as_of": metrics["as_of"],
                "benchmark_code": benchmark_code,
                "ret_1y": metrics["ret_1y"],
                "ret_3y": metrics["ret_3y"],
                "ret_5y": metrics["ret_5y"],
                "ytd": metrics["ytd"],
                "ann_vol_1y": metrics["ann_vol_1y"],
                "max_dd_1y": metrics["max_dd_1y"],
                "tracking_error_1y": metrics["tracking_error_1y"],
                "info_ratio_1y": metrics["info_ratio_1y"],
                "n_obs": metrics["n_obs"],
            }
        )
        stats["metrics"][fund_code] = {
            "nav_basis": picked.basis,
            "benchmark_code": benchmark_code,
            "benchmark_basis": benchmark.basis if benchmark is not None else None,
            "tracking_error_1y": metrics["tracking_error_1y"],
            "ret_1y": metrics["ret_1y"],
            "n_obs": metrics["n_obs"],
        }
        if benchmark is not None:
            stats["benchmark_basis_counts"][benchmark.basis] += 1
        else:
            stats["benchmark_basis_counts"]["missing"] += 1
    stats["rows"] = len(rows)
    return rows, stats


_UPSERT_SQL = (
    "INSERT INTO bp_fund_risk (fund_code, as_of, benchmark_code, ret_1y, ret_3y_ann,"
    " ret_5y_ann, ytd, ann_vol_1y, max_dd_1y, tracking_error_1y, info_ratio_1y,"
    " n_obs, updated_at)"
    " VALUES (%(fund_code)s, %(as_of)s, %(benchmark_code)s, %(ret_1y)s,"
    " %(ret_3y)s, %(ret_5y)s, %(ytd)s, %(ann_vol_1y)s, %(max_dd_1y)s,"
    " %(tracking_error_1y)s, %(info_ratio_1y)s, %(n_obs)s, now())"
    " ON CONFLICT (fund_code) DO UPDATE SET"
    " as_of = EXCLUDED.as_of, benchmark_code = EXCLUDED.benchmark_code,"
    " ret_1y = EXCLUDED.ret_1y, ret_3y_ann = EXCLUDED.ret_3y_ann,"
    " ret_5y_ann = EXCLUDED.ret_5y_ann, ytd = EXCLUDED.ytd,"
    " ann_vol_1y = EXCLUDED.ann_vol_1y, max_dd_1y = EXCLUDED.max_dd_1y,"
    " tracking_error_1y = EXCLUDED.tracking_error_1y,"
    " info_ratio_1y = EXCLUDED.info_ratio_1y, n_obs = EXCLUDED.n_obs,"
    " updated_at = now()"
)


def _chunks(items: Sequence[str], size: int):
    size = max(1, int(size))
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def recompute_all(
    conn,
    *,
    fund_codes: Optional[Sequence[str]] = None,
    hsi_mode: str = "auto",
    batch_size: int = 150,
    dry_run: bool = False,
    prune: bool = False,
    verbose: bool = False,
    progress: Any = None,
) -> dict:
    """全量（或指定基金）重算 bp_fund_risk。

    - fund_codes=None：跟踪基金全集（bp_index_tracker_fund 中有净值数据者）；
    - 每批读净值 ->（必要时）读 ETF hfq -> build_risk_rows -> upsert + commit；
    - dry_run 只计算不落库；prune=True 时删除不在本次结果中的旧行。
    返回汇总 dict（可 JSON 序列化，供 --report 使用）。
    """
    started = time.perf_counter()
    if hsi_mode not in HSI_BASIS_CHOICES:
        raise ValueError(f"未知 hsi_mode={hsi_mode!r}，可选: {', '.join(HSI_BASIS_CHOICES)}")

    primary = load_primary_index(conn, fund_codes)
    missing = sorted(set(fund_codes) - set(primary)) if fund_codes else []
    universe = sorted(set(fund_codes) - set(missing)) if fund_codes else sorted(primary)
    benchmarks = load_benchmark_returns(conn, sorted(set(primary.values())), hsi_mode=hsi_mode)

    basis_counts: Counter = Counter()
    benchmark_basis_counts: Counter = Counter()
    repair_events: list[dict] = []
    nav_split_events: list[dict] = []
    skipped: list[dict] = [
        {"fund_code": code, "reason": "no_tracker_index"} for code in missing
    ]
    fund_details: dict[str, dict] = {}
    rows_written = 0
    total_rows = 0
    for batch in _chunks(universe, batch_size):
        nav_rows = load_fund_nav(conn, batch)
        if nav_rows.empty:
            skipped.extend({"fund_code": code, "reason": "no_nav"} for code in batch)
            continue
        present = set(nav_rows["fund_code"])
        skipped.extend(
            {"fund_code": code, "reason": "no_nav"} for code in batch if code not in present
        )
        need_etf: list[str] = []
        for fund_code, part in nav_rows.groupby("fund_code"):
            if _need_etf_fallback(part):
                need_etf.append(normalize_etf_code(str(fund_code)))
        etf_series = load_etf_hfq(conn, need_etf) if need_etf else {}
        rows, stats = build_risk_rows(nav_rows, etf_series, primary, benchmarks)
        total_rows += len(rows)
        basis_counts.update(stats["nav_basis_counts"])
        benchmark_basis_counts.update(stats["benchmark_basis_counts"])
        repair_events.extend(stats["repair_events"])
        nav_split_events.extend(stats["nav_split_events"])
        skipped.extend(stats["skipped"])
        fund_details.update(stats["metrics"])
        if not dry_run and rows:
            with conn.cursor() as cur:
                cur.executemany(_UPSERT_SQL, rows)
            conn.commit()
            rows_written += len(rows)
        if progress is not None:
            progress(rows_written, total_rows)
        if verbose:
            print(
                f"batch {batch[0]}..{batch[-1]}: rows={len(rows)} written={rows_written}",
                flush=True,
            )

    pruned = 0
    if prune and not dry_run:
        keep = sorted(fund_details)
        with conn.cursor() as cur:
            if keep:
                cur.execute("DELETE FROM bp_fund_risk WHERE NOT (fund_code = ANY(%s))", (keep,))
            else:
                cur.execute("DELETE FROM bp_fund_risk")
            pruned = int(cur.rowcount or 0)
        conn.commit()

    elapsed = time.perf_counter() - started
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hsi_mode": hsi_mode,
        "universe_size": len(universe),
        "funds_computed": len(fund_details),
        "rows_written": rows_written,
        "rows_computed": total_rows,
        "pruned": pruned,
        "dry_run": dry_run,
        "elapsed_seconds": round(elapsed, 2),
        "nav_basis_counts": dict(basis_counts),
        "benchmark_basis_counts": dict(benchmark_basis_counts),
        "repair_events": repair_events,
        "nav_split_events": nav_split_events,
        "skipped": skipped,
        "funds": fund_details,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fund",
        action="append",
        default=None,
        help="只重算指定基金（可重复 / 逗号分隔，如 --fund SH513660,SZ159920）",
    )
    parser.add_argument(
        "--hsi-basis",
        choices=HSI_BASIS_CHOICES,
        default="auto",
        help="HSI 基准口径：auto（全收益->价格xHKDCNY）/ hsi_total_return / price_x_hkdcny / price",
    )
    parser.add_argument("--batch-size", type=int, default=150)
    parser.add_argument("--dry-run", action="store_true", help="只计算不写库")
    parser.add_argument("--prune", action="store_true", help="删除不在本次结果中的 bp_fund_risk 旧行")
    parser.add_argument("--report", type=str, default=None, help="把汇总 + 断点明细写入 JSON 文件")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    fund_codes: Optional[list[str]] = None
    if args.fund:
        fund_codes = [
            item.strip()
            for chunk in args.fund
            for item in str(chunk).split(",")
            if item.strip()
        ]

    cfg = load_config()
    with connect(cfg.db) as conn:
        summary = recompute_all(
            conn,
            fund_codes=fund_codes,
            hsi_mode=args.hsi_basis,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            prune=args.prune,
            verbose=args.verbose,
        )

    if fund_codes and len(fund_codes) == 1:
        one = fund_codes[0]
        detail = summary["funds"].get(one)
        if detail:
            print(
                "{one}: nav_basis={nav} benchmark={bench}({bb}) TE_1y={te} ret_1y={ret}".format(
                    one=one,
                    nav=detail["nav_basis"],
                    bench=detail["benchmark_code"],
                    bb=detail["benchmark_basis"],
                    te=detail["tracking_error_1y"],
                    ret=detail["ret_1y"],
                ),
                flush=True,
            )
        else:
            print(f"{one}: 未计算（skipped={summary['skipped']}）", flush=True)

    print(
        "fund_risk: universe={universe} computed={computed} rows_written={written} "
        "hsi_mode={mode} nav_basis={bases} benchmark_basis={bb} "
        "repairs={repairs} nav_splits={splits} skipped={skipped} elapsed={elapsed}s".format(
            universe=summary["universe_size"],
            computed=summary["funds_computed"],
            written=summary["rows_written"],
            mode=summary["hsi_mode"],
            bases=summary["nav_basis_counts"],
            bb=summary["benchmark_basis_counts"],
            repairs=len(summary["repair_events"]),
            splits=len(summary["nav_split_events"]),
            skipped=len(summary["skipped"]),
            elapsed=summary["elapsed_seconds"],
        ),
        flush=True,
    )
    if summary["repair_events"]:
        print(
            "净值断点修正（level_shift/spike_removed）: "
            + ", ".join(
                "{code}@{day}({kind})".format(
                    code=e["fund_code"], day=e["trade_date"], kind=e["kind"]
                )
                for e in summary["repair_events"][:10]
            )
            + (" ..." if len(summary["repair_events"]) > 10 else ""),
            flush=True,
        )
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"report: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
