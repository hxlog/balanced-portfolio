"""Binance 历史补采：OI / 多空比 / 主动买卖比 / 标记价（近 30 天）+ 日线 + 资金费率。

背景：5 分钟快照从 2026-11-14 才开始积累，30 天分位显示「样本积累中」。
Binance 的 /futures/data/* 与 /fapi/v1/* 接口支持回补最近 30 天（按 1h 粒度），
本脚本把历史数据写入同一张 snapshot_5m（幂等 upsert，不覆盖已有字段），
再触发分位重算 + API 缓存失效。

生产服务器无法直连 Binance，需要 BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809（bp-relay）。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

from bp_ingest.config import load_config, setup_logging
from bp_ingest.crypto_futures import (
    FUNDING_RATE,
    GLOBAL_LONG_SHORT,
    KLINE,
    OI_HIST,
    TAKER_LONG_SHORT,
    _get_json,
    _to_float,
    _to_utc_datetime,
    compute_percentiles,
)
from bp_ingest.db import connect

DAYS = int(os.getenv("BP_CRYPTO_BACKFILL_DAYS", "30"))
PERIOD = "1h"
PERIOD_MS = 3600 * 1000
LIMIT = 500

SNAPSHOT_SQL = """
    INSERT INTO bp_crypto_futures_snapshot_5m
        (contract_code, captured_at, mark_price, index_price, oi_contracts,
         oi_notional, long_short_ratio, taker_buy_sell_ratio, basis_pct)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (contract_code, captured_at) DO UPDATE SET
        mark_price = COALESCE(EXCLUDED.mark_price, bp_crypto_futures_snapshot_5m.mark_price),
        index_price = COALESCE(EXCLUDED.index_price, bp_crypto_futures_snapshot_5m.index_price),
        oi_contracts = COALESCE(EXCLUDED.oi_contracts, bp_crypto_futures_snapshot_5m.oi_contracts),
        oi_notional = COALESCE(EXCLUDED.oi_notional, bp_crypto_futures_snapshot_5m.oi_notional),
        long_short_ratio = COALESCE(EXCLUDED.long_short_ratio, bp_crypto_futures_snapshot_5m.long_short_ratio),
        taker_buy_sell_ratio = COALESCE(EXCLUDED.taker_buy_sell_ratio, bp_crypto_futures_snapshot_5m.taker_buy_sell_ratio),
        basis_pct = COALESCE(EXCLUDED.basis_pct, bp_crypto_futures_snapshot_5m.basis_pct)
"""

DAILY_SQL = """
    INSERT INTO bp_crypto_contract_daily
        (contract_code, trade_date, open, high, low, close, volume, quote_volume,
         funding_rate, oi_close, oi_notional_close)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (contract_code, trade_date) DO UPDATE SET
        open = COALESCE(EXCLUDED.open, bp_crypto_contract_daily.open),
        high = COALESCE(EXCLUDED.high, bp_crypto_contract_daily.high),
        low = COALESCE(EXCLUDED.low, bp_crypto_contract_daily.low),
        close = COALESCE(EXCLUDED.close, bp_crypto_contract_daily.close),
        volume = COALESCE(EXCLUDED.volume, bp_crypto_contract_daily.volume),
        quote_volume = COALESCE(EXCLUDED.quote_volume, bp_crypto_contract_daily.quote_volume),
        funding_rate = COALESCE(EXCLUDED.funding_rate, bp_crypto_contract_daily.funding_rate),
        oi_close = COALESCE(EXCLUDED.oi_close, bp_crypto_contract_daily.oi_close),
        oi_notional_close = COALESCE(EXCLUDED.oi_notional_close, bp_crypto_contract_daily.oi_notional_close),
        updated_at = now()
"""


def _window() -> tuple[int, int]:
    end = int(time.time() * 1000)
    start = end - DAYS * 24 * 3600 * 1000
    return start, end


def _paginate(path: str, symbol: str, start: int, end: int, value_key: str) -> list[dict]:
    items: list[dict] = []
    cursor = start
    while cursor < end:
        payload = _get_json(
            path,
            {"symbol": symbol, "period": PERIOD, "limit": LIMIT, "startTime": cursor, "endTime": end},
            timeout=40,
            retries=3,
        )
        if not isinstance(payload, list) or not payload:
            break
        items.extend(payload)
        last = payload[-1]
        try:
            last_ts = int(last["timestamp"])
        except (KeyError, TypeError, ValueError):
            break
        if last_ts <= cursor:
            break
        cursor = last_ts + PERIOD_MS
        if len(payload) < LIMIT:
            break
        time.sleep(0.25)
    return items


def _paginate_klines(symbol: str, start: int, end: int) -> list[list]:
    items: list[list] = []
    cursor = start
    while cursor < end:
        payload = _get_json(
            KLINE,
            {"symbol": symbol, "interval": PERIOD, "limit": LIMIT, "startTime": cursor, "endTime": end},
            timeout=40,
            retries=3,
        )
        if not isinstance(payload, list) or not payload:
            break
        items.extend(payload)
        last_ts = int(payload[-1][0])
        if last_ts <= cursor:
            break
        cursor = last_ts + PERIOD_MS
        if len(payload) < LIMIT:
            break
        time.sleep(0.25)
    return items


def backfill_contract(conn, contract_code: str) -> dict:
    start, end = _window()
    symbol = contract_code
    bucket: dict[int, dict] = {}

    def slot(ms: int) -> dict:
        return bucket.setdefault(
            ms,
            {
                "mark_price": None,
                "index_price": None,
                "oi_contracts": None,
                "oi_notional": None,
                "long_short_ratio": None,
                "taker_buy_sell_ratio": None,
                "basis_pct": None,
            },
        )

    # 标记价（1h K 线收盘）
    for row in _paginate_klines(symbol, start, end):
        try:
            slot(int(row[0]))["mark_price"] = _to_float(row[4])
        except (IndexError, TypeError, ValueError):
            continue

    # OI（1h）
    for item in _paginate(OI_HIST, symbol, start, end, "sumOpenInterest"):
        ts = _to_utc_datetime(item.get("timestamp"))
        contracts = _to_float(item.get("sumOpenInterest"))
        notional = _to_float(item.get("sumOpenInterestValue"))
        if ts is None or (contracts is None and notional is None):
            continue
        cell = slot(int(ts.timestamp() * 1000))
        cell["oi_contracts"] = contracts
        cell["oi_notional"] = notional

    # 多空比（1h）
    for item in _paginate(GLOBAL_LONG_SHORT, symbol, start, end, "longShortRatio"):
        ts = _to_utc_datetime(item.get("timestamp"))
        ratio = _to_float(item.get("longShortRatio"))
        if ts is None or ratio is None:
            continue
        slot(int(ts.timestamp() * 1000))["long_short_ratio"] = ratio

    # 主动买卖比（1h）
    for item in _paginate(TAKER_LONG_SHORT, symbol, start, end, "buySellRatio"):
        ts = _to_utc_datetime(item.get("timestamp"))
        ratio = _to_float(item.get("buySellRatio"))
        if ts is None or ratio is None:
            continue
        slot(int(ts.timestamp() * 1000))["taker_buy_sell_ratio"] = ratio

    rows = []
    for ms, cell in sorted(bucket.items()):
        if all(value is None for value in cell.values()):
            continue
        rows.append((contract_code, datetime.fromtimestamp(ms / 1000, tz=timezone.utc),
                     cell["mark_price"], cell["index_price"], cell["oi_contracts"],
                     cell["oi_notional"], cell["long_short_ratio"],
                     cell["taker_buy_sell_ratio"], cell["basis_pct"]))

    with conn.cursor() as cur:
        if rows:
            cur.executemany(SNAPSHOT_SQL, rows)

    # 日线 + 资金费率
    funding = _get_json(FUNDING_RATE, {"symbol": symbol, "limit": 1000}, timeout=40, retries=3)
    funding_by_day: dict = {}
    if isinstance(funding, list):
        for item in funding:
            ts = _to_utc_datetime(item.get("fundingTime"))
            rate = _to_float(item.get("fundingRate"))
            if ts is None or rate is None:
                continue
            day = ts.date()
            funding_by_day.setdefault(day, []).append(rate)
    daily = _paginate_klines_daily(symbol, start, end)
    daily_rows = []
    for day, (open_, high, low, close, volume, quote_volume) in sorted(daily.items()):
        rates = funding_by_day.get(day) or []
        funding_mean = sum(rates) / len(rates) if rates else None
        daily_rows.append((contract_code, day, open_, high, low, close, volume, quote_volume,
                           funding_mean, None, None))
    with conn.cursor() as cur:
        if daily_rows:
            cur.executemany(DAILY_SQL, daily_rows)

    return {"contract": contract_code, "snapshot_rows": len(rows), "daily_rows": len(daily_rows)}


def _paginate_klines_daily(symbol: str, start: int, end: int) -> dict:
    """1d K 线 → {date: (open, high, low, close, volume, quote_volume)}。"""
    out: dict = {}
    cursor = start - 24 * 3600 * 1000
    while cursor < end:
        payload = _get_json(
            KLINE,
            {"symbol": symbol, "interval": "1d", "limit": 200, "startTime": cursor, "endTime": end},
            timeout=40,
            retries=3,
        )
        if not isinstance(payload, list) or not payload:
            break
        for row in payload:
            try:
                ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
                out[ts.date()] = (
                    _to_float(row[1]), _to_float(row[2]), _to_float(row[3]), _to_float(row[4]),
                    _to_float(row[5]), _to_float(row[7]),
                )
            except (IndexError, TypeError, ValueError):
                continue
        last_ts = int(payload[-1][0])
        if last_ts <= cursor:
            break
        cursor = last_ts + 24 * 3600 * 1000
        if len(payload) < 200:
            break
        time.sleep(0.25)
    return out


def main() -> int:
    setup_logging()
    app = load_config()
    proxy = (os.getenv("BP_BINANCE_HTTP_PROXY") or "").strip()
    print("proxy:", proxy or "(direct)", "days:", DAYS, flush=True)
    started = time.time()
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute("SELECT contract_code FROM bp_crypto_contract ORDER BY contract_code LIMIT 40")
        contracts = [row[0] for row in cur.fetchall()]
    print("contracts:", len(contracts), flush=True)

    total_snapshots = 0
    total_daily = 0
    for index, contract in enumerate(contracts):
        try:
            with connect(app.db) as conn:
                conn.autocommit = False
                result = backfill_contract(conn, contract)
                conn.commit()
            total_snapshots += result["snapshot_rows"]
            total_daily += result["daily_rows"]
            print("ok", contract, "snap=", result["snapshot_rows"], "daily=", result["daily_rows"],
                  "elapsed=%.0fs" % (time.time() - started), flush=True)
        except Exception as exc:  # noqa: BLE001
            print("fail", contract, type(exc).__name__, str(exc)[:160], flush=True)
            time.sleep(1)

    print("backfill done snapshots=%d daily=%d elapsed=%.0fs" % (
        total_snapshots, total_daily, time.time() - started), flush=True)

    with connect(app.db) as conn:
        result = compute_percentiles(conn)
        conn.commit()
    print("percentiles:", result, flush=True)

    try:
        from bp_api.crypto import invalidate_crypto_cache
        invalidate_crypto_cache()
        print("cache invalidated", flush=True)
    except Exception as exc:  # noqa: BLE001
        print("cache invalidate skipped:", type(exc).__name__, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
