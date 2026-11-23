"""注册表/配置骨架测试（T2）。"""
from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from bp_etl.config import load_etl_config
from bp_etl.registry import (
    REGISTRY,
    SOURCES,
    DatasetSpec,
    RegistryError,
    validate_registry,
)


def test_p1_registry_is_valid_and_complete() -> None:
    validate_registry(REGISTRY, SOURCES)
    assert {"a_stock", "hk_stock", "etf", "fund_nav"} <= set(REGISTRY)
    for spec in REGISTRY.values():
        assert "qfq" not in spec.adjust_modes
        for adjust in spec.adjust_modes:
            assert spec.anchor[adjust]
            assert spec.target_time[adjust] >= spec.schedule_start[adjust]


def test_default_anchors_match_existing_history_basis() -> None:
    # D1：A 股 hfq 锚定新浪（与 11-13 前历史同基准）、ETF/HK hfq 锚定腾讯
    assert REGISTRY["a_stock"].anchor["hfq"] == "sina_kline"
    assert REGISTRY["etf"].anchor["hfq"] == "tencent_kline"
    assert REGISTRY["hk_stock"].anchor["hfq"] == "tencent_hk_kline"
    assert REGISTRY["a_stock"].anchor["bfq"] == "tencent_qt"


def test_registry_rejects_missing_anchor() -> None:
    bad = replace(REGISTRY["a_stock"], anchor={"bfq": "tencent_qt"})
    with pytest.raises(RegistryError, match="缺少锚定源"):
        validate_registry({"a_stock": bad}, SOURCES)


def test_registry_rejects_qfq() -> None:
    bad = replace(
        REGISTRY["a_stock"],
        adjust_modes=("bfq", "qfq"),
        anchor={"bfq": "tencent_qt", "qfq": "tencent_kline"},
        fallback={"bfq": (), "qfq": ()},
        schedule_start={"bfq": time(15, 15), "qfq": time(15, 15)},
        target_time={"bfq": time(15, 30), "qfq": time(16, 30)},
    )
    with pytest.raises(RegistryError, match="qfq"):
        validate_registry({"a_stock": bad}, SOURCES)


def test_registry_rejects_unknown_source() -> None:
    bad = replace(
        REGISTRY["a_stock"],
        anchor={"bfq": "tencent_qt", "hfq": "not_exists"},
    )
    with pytest.raises(RegistryError, match="未注册"):
        validate_registry({"a_stock": bad}, SOURCES)


def test_config_defaults_are_conservative(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "BP_ETL_MODE", "BP_ETL_WORKERS", "BP_ETL_RELAY_SG",
        "BP_ETL_RELAY2", "BP_ETL_REBUILD_START", "BP_ETL_REBUILD_END",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = load_etl_config()
    assert cfg.mode == "off"
    assert cfg.write_enabled is False
    assert 1 <= cfg.workers <= 8
    assert cfg.relay_sg is None
    assert cfg.relay_prologue is None


def test_config_mode_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BP_ETL_MODE", "bogus")
    assert load_etl_config().mode == "off"
    monkeypatch.setenv("BP_ETL_MODE", "shadow")
    cfg = load_etl_config()
    assert cfg.mode == "shadow"
    assert cfg.write_enabled is False
