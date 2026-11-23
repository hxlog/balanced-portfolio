"""dataset runner 注册入口：orchestrator/CLI 按名称取用。"""

from __future__ import annotations

from bp_etl.datasets.a_stock import AStockRunner
from bp_etl.datasets.etf import ETFRunner
from bp_etl.datasets.fund_nav import FundNavRunner
from bp_etl.datasets.hk_stock import HKStockRunner
from bp_etl.datasets.legacy_index import LegacyIndexRunner




def get_runners(config: object | None = None) -> dict[str, object]:
    """构造四类新数据集 + 旧行情链 runner；legacy 需要 relay 通道时由 config 注入。"""
    relay = getattr(config, "relay_sg", None)
    runners = [AStockRunner(), HKStockRunner(), ETFRunner(), FundNavRunner(),
               LegacyIndexRunner(relay_proxy=relay)]
    return {runner.spec.name: runner for runner in runners}