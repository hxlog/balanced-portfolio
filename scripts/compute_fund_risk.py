# -*- coding: utf-8 -*-
"""计算基金风险指标（基于净值序列，vs 主跟踪指数）→ bp_fund_risk。"""
from __future__ import annotations

import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

from bp_ingest.config import load_config
from bp_ingest.db import connect

TRADING_DAYS = 252


def load_primary_index(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (fund_code) fund_code, index_code FROM ("
            "  SELECT fund_code, index_code, sum(aum) AS s FROM bp_index_tracker_fund"
            "  GROUP BY 1, 2) t ORDER BY fund_code, s DESC NULLS LAST"
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def load_index_returns(conn, codes: set[str]) -> dict[str, pd.Series]:
    if not codes:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, trade_date, close FROM bp_index_quote_daily"
            " WHERE symbol = ANY(%s) AND adjust = 'bfq' ORDER BY symbol, trade_date",
            (list(codes),),
        )
        rows = cur.fetchall()
    frame = pd.DataFrame(rows, columns=["symbol", "trade_date", "close"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    out = {}
    for symbol, part in frame.groupby("symbol"):
        part = part.drop_duplicates(subset=["trade_date"], keep="last").set_index("trade_date").sort_index()
        close = pd.to_numeric(part["close"], errors="coerce").dropna()
        out[symbol] = close.pct_change().dropna()
    return out


def metrics(nav: pd.Series, index_ret: pd.Series | None):
    nav = nav.sort_index().dropna()
    if len(nav) < 60:
        return None
    last = nav.index[-1]
    out = {"as_of": last.date(), "n_obs": int(len(nav))}
    # YTD
    year_start = date(last.year - 1, 12, 31)
    prior = nav[nav.index.date <= year_start]
    out["ytd"] = round(float(nav.iloc[-1] / prior.iloc[-1] - 1) * 100, 4) if len(prior) else None
    for label, days, annualize in (("1y", TRADING_DAYS, False), ("3y", TRADING_DAYS * 3, True), ("5y", TRADING_DAYS * 5, True)):
        if len(nav) <= days:
            out["ret_" + label] = None
            continue
        total = float(nav.iloc[-1] / nav.iloc[-days - 1])
        years = days / TRADING_DAYS
        out["ret_" + label] = round(((total ** (1 / years) - 1) if annualize else (total - 1)) * 100, 4)
    window = nav.iloc[-TRADING_DAYS:] if len(nav) > TRADING_DAYS else nav
    rets = window.pct_change().dropna()
    out["ann_vol_1y"] = round(float(rets.std() * np.sqrt(TRADING_DAYS)) * 100, 4) if len(rets) > 10 else None
    cummax = window.cummax()
    out["max_dd_1y"] = round(float((window / cummax - 1).min()) * 100, 4)
    if index_ret is not None and len(index_ret) > 60:
        fund_ret = nav.pct_change().dropna()
        joined = pd.concat([fund_ret.rename("fund"), index_ret.rename("bench")], axis=1).dropna()
        tail = joined.iloc[-TRADING_DAYS:]
        if len(tail) > 60:
            diff = tail["fund"] - tail["bench"]
            te = float(diff.std() * np.sqrt(TRADING_DAYS))
            out["tracking_error_1y"] = round(te * 100, 4)
            if te > 1e-9 and out.get("ret_1y") is not None:
                bench_total = float((1 + tail["bench"]).prod())
                bench_ann = bench_total ** (TRADING_DAYS / len(tail)) - 1
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


def main() -> int:
    cfg = load_config()
    with connect(cfg.db) as conn:
        primary = load_primary_index(conn)
        index_returns = load_index_returns(conn, set(primary.values()))
        cur = conn.cursor()
        cur.execute("SELECT fund_code, trade_date, nav FROM bp_fund_nav_daily ORDER BY fund_code, trade_date")
        rows = cur.fetchall()
    frame = pd.DataFrame(rows, columns=["fund_code", "trade_date", "nav"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    payload = []
    for fund_code, part in frame.groupby("fund_code"):
        nav = pd.to_numeric(part.set_index("trade_date")["nav"], errors="coerce").dropna()
        benchmark = primary.get(fund_code)
        result = metrics(nav, index_returns.get(benchmark) if benchmark else None)
        if not result:
            continue
        result["fund_code"] = fund_code
        result["benchmark_code"] = benchmark
        payload.append(result)
    if payload:
        columns = ["fund_code", "as_of", "benchmark_code", "ret_1y", "ret_3y", "ret_5y", "ytd",
                   "ann_vol_1y", "max_dd_1y", "tracking_error_1y", "info_ratio_1y", "n_obs"]
        with connect(cfg.db) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO bp_fund_risk (fund_code, as_of, benchmark_code, ret_1y, ret_3y_ann, ret_5y_ann,"
                    " ytd, ann_vol_1y, max_dd_1y, tracking_error_1y, info_ratio_1y, n_obs, updated_at)"
                    " VALUES (%(fund_code)s, %(as_of)s, %(benchmark_code)s, %(ret_1y)s, %(ret_3y)s, %(ret_5y)s,"
                    " %(ytd)s, %(ann_vol_1y)s, %(max_dd_1y)s, %(tracking_error_1y)s, %(info_ratio_1y)s, %(n_obs)s, now())"
                    " ON CONFLICT (fund_code) DO UPDATE SET"
                    " as_of = EXCLUDED.as_of, benchmark_code = EXCLUDED.benchmark_code,"
                    " ret_1y = EXCLUDED.ret_1y, ret_3y_ann = EXCLUDED.ret_3y_ann, ret_5y_ann = EXCLUDED.ret_5y_ann,"
                    " ytd = EXCLUDED.ytd, ann_vol_1y = EXCLUDED.ann_vol_1y, max_dd_1y = EXCLUDED.max_dd_1y,"
                    " tracking_error_1y = EXCLUDED.tracking_error_1y, info_ratio_1y = EXCLUDED.info_ratio_1y,"
                    " n_obs = EXCLUDED.n_obs, updated_at = now()",
                    payload,
                )
            conn.commit()
    print("fund_risk rows:", len(payload), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
