"""dataset runner 注册入口：orchestrator/CLI 按名称取用。"""

from __future__ import annotations

from bp_etl.datasets.a_stock import AStockRunner
from bp_etl.datasets.etf import ETFRunner
from bp_etl.datasets.fund_nav import FundNavRunner
from bp_etl.datasets.hk_stock import HKStockRunner

_RUNNERS = (AStockRunner(), HKStockRunner(), ETFRunner(), FundNavRunner())


def get_runners() -> dict[str, object]:
    return {runner.spec.name: runner for runner in _RUNNERS}
