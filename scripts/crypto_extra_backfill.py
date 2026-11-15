# -*- coding: utf-8 -*-
"""回填加密合约额外数据：30 日资金费率历史 + 大户多空账户/持仓比历史。

用法：python scripts/crypto_extra_backfill.py [--days 30]
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

from bp_ingest.config import load_config
from bp_ingest.crypto_futures import (
    FUNDING_RATE,
    TOP_ACCOUNT,
    TOP_POSITION,
    _get_json,
    _to_float,
)
from bp_ingest.db import connect

UTC = timezone.utc


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_funding(app, codes: list[str], days: int) -> int:
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    total = 0
    for code in codes:
        try:
            payload = _get_json(
                FUNDING_RATE,
                {"symbol": code, "startTime": _ms(start), "endTime": _ms(now), "limit": 1000},
            )
        except Exception as exc:  # noqa: BLE001
            print("funding fail", code, type(exc).__name__, str(exc)[:80], flush=True)
            continue
        rows = []
        for item in payload or []:
            if not isinstance(item, dict):
                continue
            ts = item.get("fundingTime")
            rate = _to_float(item.get("fundingRate"))
            if ts is None or rate is None:
                continue
            rows.append((code, datetime.fromtimestamp(ts / 1000, tz=UTC), rate))
        if rows:
            with connect(app.db) as c2, c2.cursor() as cur:
                cur.executemany(
                    "INSERT INTO bp_crypto_funding_history (contract_code, funding_time, funding_rate)"
                    " VALUES (%s, %s, %s) ON CONFLICT (contract_code, funding_time) DO UPDATE SET"
                    " funding_rate = EXCLUDED.funding_rate",
                    rows,
                )
                c2.commit()
            total += len(rows)
        time.sleep(0.05)
    return total


def fetch_top_ratio(app, codes: list[str], days: int, period: str = "1h") -> int:
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    total = 0
    for path, column in ((TOP_ACCOUNT, "top_account_ratio"), (TOP_POSITION, "top_position_ratio")):
        for code in codes:
            cursor_start = _ms(start)
            rows = []
            for _ in range(4):
                try:
                    payload = _get_json(
                        path,
                        {"symbol": code, "period": period, "limit": 500, "startTime": cursor_start, "endTime": _ms(now)},
                    )
                except Exception as exc:  # noqa: BLE001
                    print("ratio fail", path, code, type(exc).__name__, str(exc)[:60], flush=True)
                    break
                batch = [item for item in (payload or []) if isinstance(item, dict)]
                if not batch:
                    break
                for item in batch:
                    ts = item.get("timestamp")
                    value = _to_float(item.get("longShortRatio"))
                    if ts is None:
                        continue
                    rows.append((code, datetime.fromtimestamp(ts / 1000, tz=UTC), value))
                last_ts = batch[-1].get("timestamp")
                if last_ts is None:
                    break
                cursor_start = int(last_ts) + 1
                if len(batch) < 500:
                    break
                time.sleep(0.05)
            if rows:
                with connect(app.db) as c2, c2.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO bp_crypto_top_ratio_history (contract_code, ts, " + column + ")"
                        " VALUES (%s, %s, %s) ON CONFLICT (contract_code, ts) DO UPDATE SET "
                        + column + " = EXCLUDED." + column,
                        rows,
                    )
                    c2.commit()
                total += len(rows)
            time.sleep(0.05)
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    cfg = load_config()
    with connect(cfg.db) as conn, conn.cursor() as cur:
        cur.execute("SELECT contract_code FROM bp_crypto_contract WHERE is_active ORDER BY oi_notional_rank NULLS LAST")
        codes = [row[0] for row in cur.fetchall()]
    print("contracts:", len(codes), flush=True)
    funding = fetch_funding(cfg, codes, args.days)
    print("funding rows:", funding, flush=True)
    ratios = fetch_top_ratio(cfg, codes, args.days)
    print("ratio rows:", ratios, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
