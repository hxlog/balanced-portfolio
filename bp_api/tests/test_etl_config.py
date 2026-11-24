"""ETL 配置：.env 的 BP_ETL_* 必须覆盖进程内过期环境变量。"""
from __future__ import annotations

import pathlib

import pytest

from bp_etl import config as config_mod


def test_dotenv_bp_etl_overrides_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BP_ETL_MODE=on\nBP_ETL_RELAY_SG=http://127.0.0.1:10809\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ENV_PATH", env_file)
    monkeypatch.setenv("BP_ETL_MODE", "off")
    cfg = config_mod.load_etl_config()
    assert cfg.mode == "on"
    assert cfg.relay_sg == "http://127.0.0.1:10809"
