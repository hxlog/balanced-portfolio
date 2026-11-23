"""e2e 验收脚本的判定逻辑测试（纯函数）。"""
from __future__ import annotations

import importlib.util
import pathlib


def _load_module():
    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "etl_e2e_acceptance.py"
    spec = importlib.util.spec_from_file_location("etl_e2e_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _payload(**overrides: object) -> dict:
    base = {
        "datasets": {
            "a_stock": {
                "bfq": {"covered": 5210, "total": 5227},
                "hfq": {"covered": 5200, "total": 5227},
                "state_ok_bfq": True,
                "state_ok_hfq": True,
                "total": 5227,
            },
            "hk_stock": {
                "bfq": {"covered": 2760, "total": 2811},
                "hfq": {"covered": 2740, "total": 2811},
                "state_ok_bfq": True,
                "state_ok_hfq": True,
                "total": 2811,
            },
            "etf": {
                "bfq": {"covered": 1350, "total": 1392},
                "hfq": {"covered": 1350, "total": 1392},
                "state_ok_bfq": True,
                "state_ok_hfq": True,
                "total": 1392,
            },
            "fund_nav": {"covered": 23931, "total": 25416, "state_ok_nav": True},
        }
    }
    if overrides:
        base["datasets"].update(overrides)  # type: ignore[union-attr]
    return base


def test_e2e_all_green() -> None:
    module = _load_module()
    ok, failures = module.evaluate(_payload())
    assert ok and failures == []


def test_e2e_flags_low_coverage_and_state() -> None:
    module = _load_module()
    bad = _payload()
    bad["datasets"]["a_stock"]["hfq"] = {"covered": 4000, "total": 5227}
    bad["datasets"]["fund_nav"]["state_ok_nav"] = False
    ok, failures = module.evaluate(bad)
    assert not ok
    assert any("a_stock:hfq" in item for item in failures)
    assert any("fund_nav" in item for item in failures)


def test_e2e_ratio_helper() -> None:
    module = _load_module()
    assert module._ratio(0, 0) == 0.0
    assert module._ratio(1, 4) == 0.25