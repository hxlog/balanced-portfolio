"""命令行入口。

用法:
  python -m bp_ingest ping                      # 测试数据库连通性
  python -m bp_ingest run                        # 执行一轮增量更新(全部标的)
  python -m bp_ingest run --symbols 000300 HSI   # 仅更新指定 symbol
  python -m bp_ingest schedule                   # 启动每6h定时调度(先跑一轮)
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import ingest, scheduler
from .config import load_config, setup_logging
from .db import ping

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bp_ingest", description="Balanced Portfolio 行情增量更新")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ping", help="测试数据库连通性")

    p_run = sub.add_parser("run", help="执行一轮增量更新")
    p_run.add_argument("--symbols", nargs="*", default=None, help="仅更新指定 symbol(空格分隔)")
    p_run.add_argument("--no-clean", action="store_true", help="跳过清洗表刷新")

    p_clean = sub.add_parser("clean", help="重建清洗表 bp_quote_clean")
    p_clean.add_argument("--symbols", nargs="*", default=None, help="仅清洗指定 symbol")

    sub.add_parser("schedule", help="启动定时调度(每6h)")

    p_cb = sub.add_parser("cffex-backfill", help="CFFEX 期货数据同步(自动增量)")
    p_cb.add_argument("--full", action="store_true", help="强制全量回填(重拉数据+重算premium)")
    p_cb.add_argument("--recompute-premium", action="store_true", help="仅重算premium(不重拉数据, 公式变更后使用)")
    sub.add_parser("cffex-incremental", help="CFFEX 期货 T-1 增量更新")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = load_config()
    setup_logging(app.log_level)

    from .http_session import install_hardened_session
    install_hardened_session()

    # 预热 EM 代码映射表(best-effort): cn_index/hk_index 的 secid 解析依赖此;
    # 掐断则自定义 fetch 走前缀探测兜底, 不阻断。
    if args.command in ("run", "schedule"):
        from .sources import prewarm_em_code_maps
        prewarm_em_code_maps()

    if args.command == "ping":
        if not app.db.password:
            logger.warning("PGPASSWORD 为空, 请在 .env 中配置密码")
        version = ping(app.db)
        logger.info("连接成功 %s", app.db.safe_repr())
        logger.info("服务器: %s", version)
        return 0

    if args.command == "run":
        results = ingest.run(app, symbols=args.symbols, refresh_clean=not args.no_clean)
        return 0 if all(r.status != "error" for r in results) else 1

    if args.command == "clean":
        from bp_api.quant.cleaning import rebuild_clean
        from . import db as _db

        with _db.connect(app.db) as conn:
            conn.autocommit = False
            n = rebuild_clean(conn, symbols=args.symbols)
        logger.info("清洗完成, 写入 %d 行", n)
        return 0

    if args.command == "schedule":
        scheduler.start(app)
        return 0

    if args.command == "cffex-backfill":
        from . import cffex as _cffex
        force_full = getattr(args, "full", False)
        recompute = getattr(args, "recompute_premium", False)
        stats = _cffex.run_backfill(force_full=force_full, recompute_premium=recompute)
        logger.info("CFFEX 同步完成: %s", stats)
        return 0

    if args.command == "cffex-incremental":
        from . import cffex as _cffex
        stats = _cffex.run_incremental()
        logger.info("CFFEX 增量更新完成: %s", stats)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
