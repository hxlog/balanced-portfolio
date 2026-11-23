# -*- coding: utf-8 -*-
"""P0 源时点研究：从 bp_etl_run 统计各 dataset/adjust 的「首次达标时刻」与目标时点偏差。

用法：
  python scripts/etl_source_timing_report.py --days 14 --out docs/data/etl-source-timing.json
输出：每个 dataset/adjust 的 p50/p95 达标延迟（分钟）与建议 SLA。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import date, datetime, time, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8")

CN = timezone(timedelta(hours=8))


def summarize_runs(rows: list[dict], targets: dict[tuple[str, str], time]) -> dict:
    """rows: [{dataset, adjust, trade_date, first_ok_at}], targets: {(dataset, adjust): 目标时点}。

    返回每 (dataset, adjust) 的延迟统计（分钟）：目标时点 → 首次达标当天时刻。
    """
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = (row["dataset"], row.get("adjust") or "nav")
        target = targets.get(key)
        first_ok_at = row["first_ok_at"]
        if target is None or first_ok_at is None:
            continue
        if isinstance(first_ok_at, str):
            first_ok_at = datetime.fromisoformat(first_ok_at)
        if first_ok_at.tzinfo is None:
            first_ok_at = first_ok_at.replace(tzinfo=CN)
        target_dt = datetime.combine(first_ok_at.astimezone(CN).date(), target, tzinfo=CN)
        delay_min = (first_ok_at.astimezone(CN) - target_dt).total_seconds() / 60.0
        grouped.setdefault(key, []).append(delay_min)
    out: dict[str, dict] = {}
    for (dataset, adjust), delays in sorted(grouped.items()):
        delays.sort()
        count = len(delays)
        p50 = delays[int(count * 0.5) - 1] if count else None
        p95 = delays[min(count - 1, int(count * 0.95))] if count else None
        out[f"{dataset}/{adjust}"] = {
            "samples": count,
            "p50_delay_min": round(p50, 1) if p50 is not None else None,
            "p95_delay_min": round(p95, 1) if p95 is not None else None,
            "target": targets[(dataset, adjust)].strftime("%H:%M"),
        }
    return out


def fetch_rows(conn, days: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT dataset, detail->>'adjust' AS adjust, trade_date, min(started_at)"
            " FROM bp_etl_run"
            " WHERE status = 'ok' AND trade_date >= current_date - %s"
            " GROUP BY dataset, detail->>'adjust', trade_date"
            " ORDER BY trade_date DESC",
            (days,),
        )
        columns = [desc[0] for desc in cur.description]
        return [
            {"dataset": row[0], "adjust": row[1], "trade_date": row[2], "first_ok_at": row[3]}
            for row in cur.fetchall()
        ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--out", default="docs/data/etl-source-timing.json")
    args = parser.parse_args(argv)

    from bp_etl.config import load_etl_config
    from bp_etl.registry import REGISTRY
    from bp_ingest.db import connect

    targets: dict[tuple[str, str], time] = {}
    for name, spec in REGISTRY.items():
        keys = ("nav",) if spec.value_kind == "nav" else spec.adjust_modes
        for key in keys:
            targets[(name, key)] = spec.target_time[key]

    config = load_etl_config()
    with connect(config.db) as conn:
        rows = fetch_rows(conn, args.days)
    report = {
        "generated_at": datetime.now(CN).isoformat(),
        "days": args.days,
        "runs": len(rows),
        "timing": summarize_runs(rows, targets),
    }
    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
