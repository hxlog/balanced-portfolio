"""一次性脚本: 用新浪 CME 期货补 BTC-USD 缺口(重锚到库中现货口径), 只补缺失日期, 不覆盖已有行。

用法: .venv\\Scripts\\python.exe scripts/backfill_btc_cme.py [--dry-run]

背景 (2026-09): yfinance BTC-USD 停更于 2026-08-27 (Yahoo 限流), crypto 看板
effective_td 被 atomicity hold-back 卡在 08-27。本脚本用 Task 2 落地的
btc_cme_sina 适配器 (ak.futures_foreign_hist("BTC"), CME 比特币期货主力) 拉全量
期货日线, 经 _align_fallback_to_base 用库中最后现货收盘 (anchor_close@anchor_date)
重锚到现货口径, 仅 INSERT 缺失日期 (ON CONFLICT DO NOTHING, 不 UPDATE/DELETE
已有行)。pct_change 留 NULL, 由 bp_ingest clean 基于清洗价重算收益率。

凭据: 从环境变量 PG* 读取 (config.load_config → load_dotenv), 不硬编码。
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bp_ingest.config import load_config  # noqa: E402
from bp_ingest.db import connect  # noqa: E402
from bp_ingest.sources import get_adapter, _align_fallback_to_base  # noqa: E402

SYMBOL = "BTC-USD"
SOURCE = "crypto_yfinance"  # 落库口径仍是主源 (期货价已重锚)
RATIO_TOL = 0.10  # 重锚 ratio 偏离 1.0 超过 ±10% → 中止 (期货/现货基差应 <~2%)
MAX_MISSING = 500  # 缺失超过 500 行视为口径问题 → 中止

logger = logging.getLogger("backfill_btc_cme")


def _clean(v) -> float | None:
    """NaN/Inf → None (psycopg 拒绝 NaN/Infinity token)。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="只打印统计, 不写库")
    args = ap.parse_args()

    # 1. 拉 CME 期货全量 (akshare 只返回全量, _finalize 按 [start,end] 过滤)
    df = get_adapter("btc_cme_sina").fetch(SYMBOL, date(2017, 1, 1), date.today(), {})
    if df is None or df.empty:
        print("FAIL: CME 期货拉取为空, 中止")
        return 1
    # 1.5 剔除非 finite close: bp_index_quote_daily.close 为 NOT NULL, _clean 会把 NaN/Inf
    # 转 None → 单行坏数据会让下方 INSERT 循环中途 NOT NULL violation 回滚整批。
    # 整行丢弃(保持 OHLC 同行一致), 不做单列置 NULL。
    finite = df["close"].map(lambda v: _clean(v) is not None)
    n_bad = int((~finite).sum())
    if n_bad:
        print(
            f"dropped {n_bad} rows with non-finite close "
            f"({df.loc[~finite, 'trade_date'].min()}..{df.loc[~finite, 'trade_date'].max()})"
        )
        df = df[finite]
        if df.empty:
            print("FAIL: 剔除非 finite close 后期货帧为空, 中止")
            return 1
    print(f"futures rows={len(df)} range={df['trade_date'].min()}..{df['trade_date'].max()}")

    # 2. 库中现货历史 (锚点)
    with connect(load_config().db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date, close FROM bp_index_quote_daily "
                "WHERE symbol=%s AND source=%s ORDER BY trade_date",
                (SYMBOL, SOURCE),
            )
            have = cur.fetchall()
        if not have:
            print("FAIL: 库中无 BTC-USD 现货历史, 无法重锚 —— 中止 (需先让 yfinance 拉一次或人工定锚)")
            return 1
        have_dates = {r[0] for r in have}
        anchor_close, anchor_date = float(have[-1][1]), have[-1][0]
        print(f"db anchor: {anchor_date} close={anchor_close}")

        # 3. 重锚到现货口径 (base_df=None → 走库中锚点分支; 周末锚点容差由
        #    _align_fallback_to_base 分支 2 处理: 精确匹配, 否则 ≤anchor_date 7 天内最近一根)
        # 3a. 锚点可用性前置检查: 若期货帧在锚点 7 天容差内无行, _align 将 no-op
        #     原样返回 → 下方 ratio 恒为 1.0 → 守卫失明, 未缩放的期货价会被当
        #     现货价写入。dry-run 与真实模式都必须先过这一关。
        prior = df[df["trade_date"] <= anchor_date]
        if prior.empty or (anchor_date - prior["trade_date"].max()).days > 7:
            print("FAIL: 锚点 7 天容差内无期货行, _align 将 no-op —— 中止(先补期货源或人工定锚)")
            return 1
        aligned = _align_fallback_to_base(None, df, anchor_close=anchor_close, anchor_date=anchor_date)

        # ratio 守卫: 对齐后锚点日收盘应 == 库中锚点收盘 (分支 2 即按此缩放)。
        # 若锚点日不在期货帧 (周末), 检查缩放是否生效: 与未缩放的期货价对比。
        unscaled_at_anchor = df[df["trade_date"] <= anchor_date]
        if not unscaled_at_anchor.empty:
            fb_close = float(unscaled_at_anchor.sort_values("trade_date").iloc[-1]["close"])
            scaled_at_anchor = aligned[aligned["trade_date"] <= anchor_date]
            sc_close = float(scaled_at_anchor.sort_values("trade_date").iloc[-1]["close"])
            ratio = sc_close / fb_close if fb_close else float("nan")
            print(f"re-anchor ratio (scaled/unscaled @ {anchor_date} 附近): {ratio:.6f}")
            if not math.isfinite(ratio) or abs(ratio - 1.0) > RATIO_TOL:
                print(f"FAIL: ratio 偏离 1.0 超过 ±{RATIO_TOL:.0%}, 疑似锚点/数据错误 —— 中止不写库")
                return 1
            # 基差合理性: 现货锚点 / 重锚所用的期货收盘 (即 ratio 本身含义的另一面)
            basis = abs(anchor_close / fb_close - 1.0) if fb_close else float("nan")
            print(f"basis |spot/futures - 1| @ anchor: {basis:.4%} (CME 期货 vs 现货基差应 <~2%)")

        # 4. 只取缺失日期 (今日未收盘确认的行剔除)
        today = date.today()
        missing = aligned[~aligned["trade_date"].isin(have_dates)]
        missing = missing[missing["trade_date"] < today]
        missing = missing.sort_values("trade_date")
        n_missing = len(missing)
        lo = missing["trade_date"].min() if n_missing else "-"
        hi = missing["trade_date"].max() if n_missing else "-"
        print(f"missing dates to insert: {n_missing} ({lo}..{hi})")

        if n_missing > MAX_MISSING:
            print(f"FAIL: missing {n_missing} > {MAX_MISSING}, 疑似口径问题 —— 中止 (预期仅尾部缺口/零星空洞)")
            return 1
        if n_missing == 0:
            print("无缺口, 无事可做")
            return 0
        if args.dry_run:
            print("DRY-RUN: 不写库。待插入行:")
            print(missing[["trade_date", "open", "high", "low", "close", "volume"]].to_string(index=False))
            return 0

        # 5. 写库: 仅 INSERT 缺失日期, ON CONFLICT DO NOTHING (不覆盖已有行)
        with conn.cursor() as cur:
            for _, r in missing.iterrows():
                cur.execute(
                    """INSERT INTO bp_index_quote_daily
                       (symbol, source, trade_date, open, high, low, close, volume, amount,
                        turnover_rate, pct_change)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,NULL)
                       ON CONFLICT (symbol, source, trade_date) DO NOTHING""",
                    (SYMBOL, SOURCE, r["trade_date"],
                     _clean(r.get("open")), _clean(r.get("high")), _clean(r.get("low")),
                     _clean(r["close"]), _clean(r.get("volume"))),
                )
        conn.commit()
    print(f"inserted {n_missing} rows ({lo}..{hi}); 注意: pct_change 为 NULL, 由 bp_ingest clean 基于清洗价重算收益率")
    return 0


if __name__ == "__main__":
    sys.exit(main())
