"""bp_etl CLI：run / service / health（rebuild/verify 由 T11 追加）。"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from bp_etl.config import load_etl_config
from bp_etl.datasets import get_runners
from bp_etl.orchestrator import Orchestrator
from bp_etl.registry import REGISTRY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bp_etl", description="统一行情 ETL")
    parser.add_argument("--log-level", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="手动执行单个 dataset 的波次（默认 1 波）")
    run_p.add_argument("--dataset", required=True, choices=sorted(REGISTRY))
    run_p.add_argument("--adjust", default=None, help="bfq/hfq；nav 数据集省略")
    run_p.add_argument("--date", default=None, help="目标交易日 YYYY-MM-DD（默认按收盘确认推断）")
    run_p.add_argument("--waves", type=int, default=1, help="连续波次数（未达标自动退避重试）")
    run_p.add_argument("--force", action="store_true", help="忽略已完成状态/退避，强制重跑")
    run_p.add_argument("--json", action="store_true", help="以 JSON 输出结果")

    sub.add_parser("service", help="常驻调度（PM2 bp-etl 使用，无限追赶）")

    health_p = sub.add_parser("health", help="打印 dataset 状态/最近运行/backlog")
    health_p.add_argument("--dataset", default=None)
    health_p.add_argument("--limit", type=int, default=10)
    return parser


def _setup_logging(level: str | None) -> None:
    logging.basicConfig(
        level=getattr(logging, (level or "INFO").upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )


def _wave_dict(result: object) -> dict:
    return {
        "dataset": getattr(result, "dataset", None),
        "adjust": getattr(result, "adjust", None),
        "trade_date": str(getattr(result, "trade_date", "")),
        "wave": getattr(result, "wave", None),
        "fetched": getattr(result, "fetched", None),
        "written": getattr(result, "written", None),
        "coverage": round(getattr(result, "coverage", 0.0), 6),
        "ok": getattr(result, "ok", None),
        "skipped": getattr(result, "skipped", None),
        "skip_reason": getattr(result, "skip_reason", ""),
    }


def cmd_run(args: argparse.Namespace) -> int:
    config = load_etl_config()
    orchestrator = Orchestrator(config, runners=get_runners())
    runner = orchestrator.runners[args.dataset]
    keys = ("nav",) if runner.spec.value_kind == "nav" else runner.spec.adjust_modes
    adjusts = [args.adjust] if args.adjust else list(keys)
    trade_date = None
    if args.date:
        from datetime import date

        trade_date = date.fromisoformat(args.date)
    results = []
    for adjust in adjusts:
        for wave in range(1, args.waves + 1):
            outcome = orchestrator.run_wave(
                args.dataset, adjust, trade_date=trade_date, wave=wave, force=args.force
            )
            results.append(_wave_dict(outcome))
            if outcome.ok or outcome.skipped:
                break
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        for item in results:
            print(item)
    return 0


def cmd_service(_args: argparse.Namespace) -> int:
    config = load_etl_config()
    if config.mode == "off":
        print("BP_ETL_MODE=off：不启动（设置 on/shadow 后再启动）")
        return 0
    Orchestrator(config, runners=get_runners()).service()
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    config = load_etl_config()
    from bp_ingest.db import connect

    with connect(config.db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT dataset, last_success_date, last_run_id, updated_at FROM bp_etl_dataset_state ORDER BY dataset")
            states = [dict(zip(("dataset", "last_success_date", "last_run_id", "updated_at"), row)) for row in cur.fetchall()]
            params: list = []
            sql = (
                "SELECT dataset, trade_date, wave, status, achieved_coverage, rows_written,"
                " started_at, finished_at FROM bp_etl_run"
            )
            if args.dataset:
                sql += " WHERE dataset = %s"
                params.append(args.dataset)
            sql += " ORDER BY run_id DESC LIMIT %s"
            params.append(args.limit)
            cur.execute(sql, params)
            runs = [dict(zip(("dataset", "trade_date", "wave", "status", "coverage", "rows", "started_at", "finished_at"), row)) for row in cur.fetchall()]
            cur.execute(
                "SELECT dataset, count(*), min(trade_date), max(trade_date) FROM bp_etl_backlog GROUP BY dataset ORDER BY dataset"
            )
            backlog = [dict(zip(("dataset", "pending", "oldest", "newest"), row)) for row in cur.fetchall()]
    payload = {
        "mode": config.mode,
        "states": [{k: (str(v) if k in ("last_success_date", "updated_at") else v) for k, v in s.items()} for s in states],
        "recent_runs": [{k: (str(v) if k in ("trade_date", "started_at", "finished_at") else v) for k, v in r.items()} for r in runs],
        "backlog": [{k: (str(v) if k in ("oldest", "newest") else v) for k, v in b.items()} for b in backlog],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.log_level)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "service":
        return cmd_service(args)
    if args.command == "health":
        return cmd_health(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
