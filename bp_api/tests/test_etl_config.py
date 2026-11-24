"""ETL 配置：.env 的 BP_ETL_* 必须覆盖进程内过期环境变量。"""
from __future__ import annotations

import importlib

from bp_etl import config as config_mod


def test_dotenv_bp_etl_overrides_env(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BP_ETL_MODE=on\nBP_ETL_RELAY_SG=http://127.0.0.1:10809\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BP_ETL_MODE", "off")
    importlib.reload(config_mod)
    cfg = config_mod.load_etl_config()
    assert cfg.mode == "on"
    assert cfg.relay_sg == "http://127.0.0.1:10809"
