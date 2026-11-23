"""行情源适配器集合（导入即注册子模块，供 `from bp_etl import adapters` 使用）。"""

from bp_etl.adapters import base, eastmoney, sina, tencent  # noqa: F401

__all__ = ["base", "eastmoney", "sina", "tencent"]
