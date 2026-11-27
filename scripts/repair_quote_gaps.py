#!/usr/bin/env python3
"""旧链行情缺口自动修补（A股/ETF/全球指数等旧源退化时的日终兜底）。

背景：旧指数链的 etf_em/etf_sina/cn_index_em/global_index_em 等源在东财 IP 封禁后
经常当日不推进，导致组合 T-1 自动更新卡在上一交易日。本脚本在每日收盘后：
1) ETF 旧源：用 v3 ETF 当日收益锚定旧链最后收盘（保持旧链复权基准不变）；
2) 仅东财可取的 CSI 指数（931xxx/932xxx/950xxx 等）：用中证官网 csindex API 补日线；
3) 恒生科技指数 HSTECH：用腾讯港股指数 K 线补；
4) HKDCNY 汇率日 K 未发布时：用新浪实时汇率收盘价补（清洗折算依赖）；
5) 重清洗受影响标的 → 刷新资产状态 → 触发 T-1 组合更新。

只补“数据可证明”的行情；美国市场休市（如感恩节）不伪造数据。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, "/opt/balanced-portfolio")

import psycopg
import requests

PRIO = {"tencent_etf_kline": 0, "sina_etf_kline:factor": 1, "tencent_kline": 2,
        "tencent_etf_kline:ratio": 3, "em_kline:anchored": 4}
CN = "https://www.csindex.com.cn/csindex-home/perf/index-perf"


def connect():
    return psycopg.connect(host="127.0.0.1", port=5432, dbname="postgres",
                           user="postgres", password=os.environ.get("PGPASSWORD", ""),
                           connect_timeout=10)


def trade_date(conn, ref: date) -> date:
    with conn.cursor() as cur:
        cur.execute("SELECT max(cal_date) FROM bp_trading_calendar WHERE market='CN' AND is_trading AND cal_date<=%s", (ref,))
        return cur.fetchone()[0]


def config(conn, symbol, source):
    with conn.cursor() as cur:
        cur.execute("SELECT coalesce(category,''), coalesce(name,''), coalesce(adjust,'bfq') FROM bp_index_config WHERE symbol=%s AND source=%s AND is_deleted=0 ORDER BY managed_by NULLS FIRST LIMIT 1", (symbol, source))
        return cur.fetchone() or ("", "", "bfq")


def upsert(conn, symbol, source, adjust, rows):
    cat, name = config(conn, symbol, source)[:2]
    with conn.cursor() as cur:
        for d, o, h, l, c, pct in rows:
            cur.execute("""
                INSERT INTO bp_index_quote_daily
                    (symbol, source, adjust, trade_date, category, name, open, high, low, close, pct_change)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (symbol, source, adjust, trade_date) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, pct_change=EXCLUDED.pct_change, updated_at=now()
            """, (symbol, source, adjust, d, cat, name, o, h, l, c, pct))
    conn.commit()


def stale_pairs(conn, td: date):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT a.symbol, a.source, s.last_clean_date
            FROM bp_portfolio_asset a
            JOIN bp_portfolio p ON p.portfolio_id = a.portfolio_id
            LEFT JOIN bp_asset_data_status s ON s.symbol=a.symbol AND s.source=a.source
            WHERE p.method = 'quadrant_inner_sharpe_outer_rp'
              AND (s.last_clean_date IS NULL OR s.last_clean_date < %s)
        """, (td,))
        return cur.fetchall()


def bridge_etf(conn, td: date, symbol, source):
    with conn.cursor() as cur:
        cur.execute("SELECT trade_date, close FROM bp_index_quote_daily WHERE symbol=%s AND source=%s AND trade_date<%s ORDER BY trade_date DESC LIMIT 1", (symbol, source, td))
        old = cur.fetchone()
        if not old:
            return False
        cur.execute("""
            SELECT source, trade_date, open, high, low, close FROM bp_etf_quote_daily
            WHERE etf_code=%s AND trade_date > %s AND trade_date <= %s AND close IS NOT NULL
        """, (symbol, td - timedelta(days=14), td))
        rows = cur.fetchall()
    by = {}
    for r in rows:
        by.setdefault(r[0], {})[r[1]] = r
    for src in sorted(by, key=lambda s: PRIO.get(s, 9)):
        d = by[src]
        dates = sorted(d)
        if len(dates) < 2:
            continue
        prev = d[dates[-2]]; tod = d[dates[-1]]
        if tod[1] != td:
            continue
        factor = float(old[1]) / float(prev[5])
        upsert(conn, symbol, source, "hfq" if config(conn, symbol, source)[2] == "hfq" else config(conn, symbol, source)[2],
               [(td, None if tod[2] is None else float(tod[2])*factor,
                 None if tod[3] is None else float(tod[3])*factor,
                 None if tod[4] is None else float(tod[4])*factor,
                 float(tod[5])*factor,
                 (float(tod[5])*factor/float(old[1])-1)*100.0)])
        return True
    return False


def fill_csi(conn, td: date, symbol, source):
    with conn.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM bp_index_quote_daily WHERE symbol=%s AND source=%s", (symbol, source))
        last = cur.fetchone()[0]
    start = (last + timedelta(days=1)) if last else (td - timedelta(days=30))
    if start > td:
        return False
    r = requests.get(CN, params={"indexCode": symbol, "startDate": start.strftime("%Y%m%d"),
                                 "endDate": td.strftime("%Y%m%d")}, timeout=30)
    r.raise_for_status()
    data = r.json().get("data") or []
    rows = []
    for row in data:
        d = date(int(row["tradeDate"][:4]), int(row["tradeDate"][4:6]), int(row["tradeDate"][6:8]))
        if d <= (last or date.min):
            continue
        rows.append((d, row.get("open"), row.get("high"), row.get("low"), row.get("close"), row.get("changePct")))
    if not rows:
        return False
    upsert(conn, symbol, source, "bfq", rows)
    return True


def fill_hstech(conn, td: date):
    r = requests.get("https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
                     "?param=hkHSTECH,day,2010-01-01,%s,10,qfq" % td.isoformat(), timeout=20)
    day = r.json()["data"]["hkHSTECH"]["day"]
    rows = []
    with conn.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM bp_index_quote_daily WHERE symbol='HSTECH' AND source='hk_index_em'")
        last = cur.fetchone()[0]
    for item in day:
        d = date.fromisoformat(item[0])
        if d <= (last or date.min) or d > td:
            continue
        o, c, h, l = float(item[1]), float(item[2]), float(item[3]), float(item[4])
        rows.append((d, o, h, l, c, None))
    if rows:
        upsert(conn, "HSTECH", "hk_index_em", "bfq", rows)
    return bool(rows)


def fill_hkd(conn, td: date):
    with conn.cursor() as cur:
        cur.execute("SELECT max(trade_date) FROM bp_quote_clean WHERE symbol='HKDCNY' AND source='fx_sina'")
        last_clean = cur.fetchone()[0]
    if last_clean and last_clean >= td:
        return False
    r = requests.get("https://hq.sinajs.cn/list=fx_shkdcny",
                     headers={"Referer": "https://finance.sina.com.cn"}, timeout=15)
    parts = r.text.split('="')[1].split(",")
    quote_day = parts[-1].strip()
    if quote_day and quote_day != td.isoformat():
        return False
    val = float(parts[1])
    with conn.cursor() as cur:
        cur.execute("SELECT close FROM bp_quote_clean WHERE symbol='HKDCNY' AND source='fx_sina' AND adjust='bfq' ORDER BY trade_date DESC LIMIT 1")
        prev = float(cur.fetchone()[0])
    pct = (val / prev - 1.0) * 100.0
    upsert(conn, "HKDCNY", "fx_sina", "bfq", [(td, val, val, val, val, pct)])
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--reconcile-backlog",
        action="store_true",
        help="同时按当前 universe 收敛 bp_etl_backlog 的旧 universe symbol 行（dry-run 只统计）",
    )
    args = ap.parse_args()
    conn = connect()
    td = args.date or trade_date(conn, date.today())
    pairs = stale_pairs(conn, td)
    print("TD", td, "stale_pairs", len(pairs), flush=True)
    fixed: list[tuple[str, str]] = []
    for symbol, source, _last in pairs:
        try:
            ok = False
            if args.dry_run:
                print("WOULD_FIX", symbol, source, flush=True)
                continue
            if source and source.startswith("etf"):
                ok = bridge_etf(conn, td, symbol, source)
            elif source in ("cn_index_em",) and symbol.isdigit():
                ok = fill_csi(conn, td, symbol, source)
            elif symbol == "HSTECH" and source == "hk_index_em":
                ok = fill_hstech(conn, td)
            if ok:
                fixed.append((symbol, source))
                print("FIXED", symbol, source, flush=True)
        except Exception as exc:  # noqa: BLE001
            print("FAIL", symbol, source, type(exc).__name__, exc, flush=True)
    # dry-run 必须严格只读：不写行情、不重建 clean、不刷新状态、不 record_freshness，
    # 也绝不 commit（以下非 dry-run 分支才允许写库）。
    fixed_hkd = False if args.dry_run else fill_hkd(conn, td)
    if args.dry_run:
        print("WOULD_FIX_HKDCNY", flush=True)
        if args.reconcile_backlog:
            _reconcile_backlog(conn, dry_run=True)
        conn.close()
        return 0
    symbols = sorted({s for s, _ in fixed})
    if fixed_hkd:
        symbols.append("HKDCNY")
    if symbols:
        from bp_api.quant.cleaning import rebuild_clean
        from bp_etl.cleaning_hook import DbTradingCalendar
        from bp_api.daily_update import refresh_all_asset_status, enqueue_ready_portfolios
        written = rebuild_clean(conn, symbols=symbols, cal=DbTradingCalendar(conn))
        conn.commit()
        refresh_all_asset_status(conn, with_count=False)
        conn.commit()
        queued = enqueue_ready_portfolios(conn)
        conn.commit()
        print("CLEAN", len(symbols), written, "QUEUED", [q["portfolio_id"] for q in queued], flush=True)
    else:
        print("NO_GAP", flush=True)
    if args.reconcile_backlog:
        _reconcile_backlog(conn, dry_run=args.dry_run)
    _record_freshness(conn)
    conn.close()
    return 0


def _reconcile_backlog(conn, *, dry_run: bool) -> None:
    """按当前 legacy universe 收敛 backlog 旧 symbol 行（11-25/26 的 9,434/9,496 空转）。

    当前 universe 口径与 bp_etl LegacyIndexRunner.universe 对齐；dry-run 只打印计数，
    不影响现有 backlog。完整的一键对账（含 clean 重建）见 scripts/repair_quote_clean.py。
    """
    from bp_etl.health import prune_backlog_symbols

    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM bp_index_config"
            " WHERE is_deleted=0 AND managed_by IS NULL ORDER BY symbol"
        )
        universe = [row[0] for row in cur.fetchall()]
    if not universe:
        print("BACKLOG_SKIP empty_universe", flush=True)
        return
    total = 0
    for adjust in ("bfq", "hfq"):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM bp_etl_backlog"
                " WHERE dataset='legacy_index' AND adjust=%s"
                " AND scope='symbol' AND NOT (symbol = ANY(%s))",
                (adjust, universe),
            )
            pending = int(cur.fetchone()[0] or 0)
        total += pending
        print("BACKLOG_STALE", adjust, pending, "dry_run" if dry_run else "apply", flush=True)
        if not dry_run and pending:
            removed = prune_backlog_symbols(conn, "legacy_index", adjust, universe)
            conn.commit()
            print("BACKLOG_PRUNED", adjust, removed, flush=True)
    print("BACKLOG_STALE_TOTAL", total, flush=True)


def _record_freshness(conn) -> None:
    """回写 index_quotes 全局新鲜度（按库内 bfq 行情最大交易日）；失败不阻断。"""
    try:
        from bp_api.freshness import record_freshness

        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(q.trade_date) FROM bp_index_quote_daily q"
                " JOIN bp_index_config c ON c.symbol=q.symbol AND c.is_deleted=0"
                " WHERE q.adjust='bfq' AND c.category='index' AND q.trade_date >= current_date - 30"
            )
            row = cur.fetchone()
        as_of = row[0] if row else None
        if as_of is not None:
            record_freshness(conn, "index_quotes", as_of, source="scripts/repair_quote_gaps.py")
            conn.commit()
    except Exception:  # noqa: BLE001 - 新鲜度增强信号，失败不影响补数
        print("FRESHNESS_SKIP", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
