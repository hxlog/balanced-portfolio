"""手动执行指数估值抓取（首次回填 / 补跑 / 排查）。

用法:
  python -m bp_ingest valuation-run            # 抓取最近交易日并落库 + 重算分位
  python -m bp_ingest valuation-run --as-of 2026-11-13
"""

from __future__ import annotations

import json
import logging
from datetime import date

from .config import load_config, setup_logging
from .db import connect
from .valuation_ingest import run_valuation_ingest

logger = logging.getLogger(__name__)


def run(cli_as_of: date | None = None) -> dict:
    app = load_config()
    with connect(app.db) as conn:
        conn.autocommit = False
        summary = run_valuation_ingest(conn, as_of=cli_as_of)
        conn.commit()
    return summary


def main(as_of: date | None = None) -> int:
    setup_logging()
    summary = run(as_of)
    logger.info("估值抓取完成: %s", json.dumps(summary, ensure_ascii=False, default=str))
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0 if not (summary.get("errors") and summary.get("indices", 0) == 0) else 1

if __name__ == "__main__":
    raise SystemExit(main())
